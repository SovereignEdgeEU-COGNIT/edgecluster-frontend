# Global Scaling Orchestrator

## Goal

The Global Scaling Orchestrator manages the lifecycle of FaaS VMs across multiple OpenNebula edge clusters. Its primary objectives are:

1. **Device-to-Cluster Assignment**: Assign new IoT devices to the most suitable edge cluster based on their requirements (latency, energy, geolocation) and cluster capacity.
2. **Automatic Scaling**: Scale clusters up when demand increases (queue depth grows) and scale down when demand decreases (queue empty, low utilization).
3. **Device Stickiness**: Keep devices assigned to their cluster unless explicit migration is needed.
4. **Capacity Management**: Enforce cluster capacity limits and trigger device migration when clusters reach maximum capacity.
5. **Load Balancing & Optimization**: Periodically rebalance device-to-cluster assignments to minimize GHG emissions while respecting SLO constraints.

---

## Components Overview

The system consists of the following components:

### 1. Global Scaling Orchestrator (Decision Layer)
- Monitors cluster metrics (queue depth, VM count) from OpenNebula monitoring and OneFlow service info
- Reads cluster attributes (flavour, max_vms) from CLUSTER template
- Computes target_cardinality per cluster based on backlog (queue depth) and capacity
- Makes scaling decisions: UP, DOWN, MIGRATE, or NOOP
- Maintains device-to-cluster mappings in SQLite
- Calls `/v1/scale` endpoint on Edge Cluster Frontends to execute scaling

### 2. Edge Cluster Frontend (Execution Layer)
- Exposes `/v1/scale?cardinality=N` endpoint (declarative, idempotent)
- Handles scale-up: calls OneGate to add VMs to the corresponding OneFlow service
- Handles scale-down: drains and terminates VMs individually (idle-first, then busy after drain)

### 3. Device-Cluster Allocation Optimizer
- Solves optimization problem to select best cluster for new devices (does NOT compute VM counts)
- Considers device requirements, cluster capacity, load distribution, CO2 policy
- Returns cluster_id for device assignment

### 4. OneDRS (OpenNebula Dynamic Resource Scheduler)
- Handles VM-level placement within a cluster (which host to use)
- Performs periodic workload optimization to minimize GHG emissions
- Operates at infrastructure level (complementary to cluster-level orchestrator)

### 5. OneFlow Services
- Each edge cluster has a OneFlow service with Frontend and FaaS VM roles
- Frontend VM: maintains queue, exposes `/v1/scale`
- FaaS VMs: execute device functions, report metrics
- Metrics (queue depth, average execution time, etc.) available via OpenNebula monitoring

### 6. SQLite Database
- Stores device-to-cluster mappings (device_id → cluster_id, flavour, last_seen, app_req_id)
- Ensures atomic device onboarding with transactional locking
- Periodically cleaned: removes devices where app_req_id is missing from OpenNebula DB or last_seen exceeds inactivity_window

---

## Component Interactions

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Global Scaling Orchestrator                        │
│  - Monitors metrics from OpenNebula monitoring & CLUSTER template       │
│  - Maintains device-cluster mappings (SQLite)                           │
│  - Computes target_cardinality per cluster                              │
│  - Makes scaling decisions (UP/DOWN/MIGRATE/NOOP)                       │
│  - Calls /v1/scale on cluster frontends                                 │
└────────┬────────────────────────────────────┬───────────────────────────┘
         │                                    │
         │ Query cluster state                │ Call /v1/scale?cardinality=N
         │ (from ON monitoring + template)    │
         ▼                                    ▼
┌──────────────────────────┐      ┌─────────────────────────────────────┐
│ Device-Cluster           │      │  Edge Cluster Frontend (per cluster)│
│ Allocation Optimizer     │      │  - Exposes /v1/scale endpoint       │
│ - Solves placement       │      │  - Calls OneFlow for scale-up       │
│ - Returns cluster_id     │      │  - Drains/terminates for scale-down │
└────────┬─────────────────┘      └────────┬────────────────────────────┘
         │                                 │
         │ Uses CO2/capacity data          │ Calls onegate commands
         ▼                                 ▼
┌──────────────────────────┐      ┌─────────────────────────────────────┐
│ OneDRS                   │      │  OneFlow Service (per cluster)      │
│ - VM placement (host)    │      │  - Frontend VM (1): queue, /v1/scale│
│ - Workload optimization  │      │  - FaaS VMs (N): execute functions  │
│ - CO2 minimization       │      └────────┬────────────────────────────┘
└──────────────────────────┘               │
                                           │ Exposes metrics
                                           ▼
                                  ┌─────────────────────────────────────┐
                                  │  OpenNebula Monitoring & Templates  │
                                  │  - Queue depth (from frontend VM)   │
                                  │  - Current cardinality (OneFlow)    │
                                  │  - Max VMs, flavour (CLUSTER tmpl)  │
                                  └─────────────────────────────────────┘

Device Request Flow (Global Endpoint):
1. Device → Global Endpoint (Orchestrator): check SQLite for device_id
2. If existing: return stored cluster_id, update last_seen
3. If new: Orchestrator gathers cluster state from OpenNebula monitoring + CLUSTER template
4. Orchestrator → Device-Cluster Optimizer: get cluster_id for device
5. Orchestrator: persist mapping (device_id, cluster_id, flavour, last_seen, app_req_id) in SQLite
6. Orchestrator: call /v1/scale on selected cluster with target_cardinality = current + 1
7. Frontend: scale OneFlow service, add VM
8. OneDRS: place VM on optimal host
9. Device → cluster Frontend: send function requests
10. Frontend: route to FaaS VM via RabbitMQ
```

---

## End-to-End Workflow (MVP)

### Device Onboarding

1. **Device request arrives** at the global endpoint with `device_id` and `Scheduling/AppRequirements`.

2. **Check SQLite**:
   - If `device_id` exists: return stored `cluster_id`, update `last_seen` timestamp.
   - If `device_id` not found: proceed to step 3.

3. **Fetch cluster snapshots** from OpenNebula:
   - Query OneFlow service info for each cluster: `current_cardinality`, service state
   - Read from OpenNebula monitoring: `queue_depth` (pending requests on frontend VM)
   - Read from CLUSTER template: `max_vms`, `flavour`, capacity constraints

4. **Select cluster**:
   - Call Device-Cluster Allocation Optimizer with:
     - Device `Scheduling/AppRequirements` (flavour, max_latency, max_exec_time, min_renewable, geolocation)
     - Cluster state snapshot (current_cardinality, queue_depth, max_vms, flavour, CO2 metrics)
   - Optimizer returns `cluster_id` or None
   - Fallback: if Optimizer unavailable or returns None, pick least-loaded eligible cluster under `max_vms` that meets device requirements
   - Edge case: if no cluster has headroom:
     - Option A: create new cluster
     - Option B: device waits until cluster frees up

5. **Persist stickiness atomically**:
   - BEGIN IMMEDIATE transaction
   - Insert row: `device_id → cluster_id, flavour, last_seen, app_req_id`
   - Acquire exclusive lock on device_id row to prevent duplicate VM provisioning
   - COMMIT

6. **Trigger scale-up**:
   - Compute `target_cardinality = current_cardinality + 1` (respect `max_vms`)
   - Call `/v1/scale?cardinality=target` on the selected cluster's frontend
   - If OneFlow in cooldown or ongoing scaling: enqueue in `pending_action_queue[cluster_id]` (coalesce to latest target)

7. **Return cluster_id** to caller (device sends subsequent function requests to that cluster's frontend).

### Periodic Orchestrator Loop (Every evaluation_interval, e.g., 30s)

1. **For each cluster**:
   - Fetch from OpenNebula: `current_cardinality`, `queue_depth` (backlog), `max_vms`
   - Compute `backlog = queue_depth`
   - Compute target:
     - If `backlog > 0`: `target_cardinality = min(current_cardinality + backlog, max_vms)`
     - If `backlog == 0` for K consecutive intervals: `target_cardinality = 1` (min_pool_size)
     - Else: `target_cardinality = current_cardinality` (NOOP)

2. **Execute or queue scaling**:
   - If `target_cardinality != current_cardinality`:
     - Else: call `/v1/scale?cardinality=target`
    - If cooldown/ongoing: update `pending_action_queue[cluster_id] = target` (keep latest)

3. **Process pending action queue**:
   - For each cluster with pending target:
     - Retry `/v1/scale?cardinality=pending_target`
     - If success: remove from queue
     - If cooldown: keep queued
     - If refusal or max_retries exceeded: alert and remove from queue

### Database Cleaning (Periodic Task, e.g., every hour)

1. **Time-triggered sweep**:
   - For each row in SQLite:
     - Check if `app_req_id` exists in OpenNebula database
     - If missing OR `last_seen > inactivity_window`: delete row
   - No immediate cluster downscale; rely on periodic orchestrator loop (backlog==0) to reduce to min_pool_size

### Pending Action Queue Semantics (summary)

- **Structure**: `{cluster_id: latest_target_cardinality}`
- **Coalescing**: if multiple scale requests arrive during cooldown, keep only the latest target (declarative, idempotent)
- **Retry**: every `evaluation_interval` until accepted or `max_retries` exceeded
- See component section “Pending Action Queue (OneFlow Cooldown Handling)” for details

---

## Detailed Component Specifications

### Global Scaling Orchestrator

```
Description:
Central decision-making component that monitors all clusters and makes scaling decisions at regular intervals (evaluation_interval). Enforces device stickiness and capacity limits. Computes target_cardinality per cluster based on backlog (queue_depth from OpenNebula monitoring).

Decision types:
- UP: backlog > 0 → call /v1/scale with increased target_cardinality
- DOWN: backlog == 0 for K consecutive intervals → call /v1/scale with target_cardinality = min_pool_size (1)
- MIGRATE: Cluster at max capacity → move devices to another cluster with headroom (deferred in MVP)
- NOOP: System in steady state

Parameters:
- evaluation_interval: How often to evaluate (e.g., 30s)
- min_pool_size: Minimum VMs per cluster (default: 1)
- K: Number of consecutive zero-backlog intervals before scale-down (e.g., 3)
- saturated_ttl: Time to keep cluster marked saturated after capacity refusal (e.g., 5 min)
- max_retries: Maximum retries for pending actions before alerting
- sqlite_db_path: Device-cluster mapping database
- optimizer_endpoint: Device-Cluster Allocation Optimizer API

Returns:
Executes decisions by calling /v1/scale. Logs: {action, cluster_id, target_cardinality, reason}
```

### Device Onboarding & Stickiness

```
Description:
All device requests arrive at a single global endpoint. For each request, check SQLite. If existing: return stored cluster_id, update last_seen. If new: gather cluster state from OpenNebula monitoring + CLUSTER template, call Optimizer for cluster_id, persist mapping atomically, trigger scale-up (+1 VM). Devices remain sticky unless orchestrator migrates them. See “End-to-End Workflow (MVP)” for the ordered steps.

Flow for new device:
1. Collect device Scheduling/AppRequirements (flavour, max_latency, max_exec_time, min_renewable, geolocation)
2. Gather cluster state from OpenNebula: queue_depth (monitoring), current_cardinality (OneFlow service info), max_vms/flavour (CLUSTER template), CO2 data
3. Call Device-Cluster Allocation Optimizer → returns cluster_id or None
4. Fallback: if None, pick least-loaded eligible cluster; if all saturated, wait/backpressure
5. Atomically persist mapping in SQLite: device_id → cluster_id, flavour, last_seen, app_req_id
6. Call /v1/scale with target_cardinality = current_cardinality + 1

Parameters:
- device_id, Scheduling (AppRequirements), request_timestamp, app_req_id

Returns:
cluster_id
```

### SQLite Concurrency Control

```
Description:
Uses transactional boundaries (BEGIN IMMEDIATE) and row-level locking to ensure atomic device onboarding. A dedicated lock table prevents duplicate VM provisioning for concurrent requests. 

Cleanup: Periodic background task checks each row:
- If app_req_id missing in OpenNebula database: delete row
- If last_seen > inactivity_window: delete row
- No immediate downscale; periodic orchestrator loop (backlog==0 for K intervals) reduces to min_pool_size

Parameters:
- db_path, inactivity_window (e.g., 24h), cleanup_interval (e.g., 1h)

Returns:
Transaction result: success or retry on conflict
```

### Pending Action Queue (OneFlow Cooldown Handling)

```
Description:
OneFlow enforces cooldown between scaling operations. To avoid losing scale requests during cooldown, the orchestrator maintains a pending_action_queue per cluster. Failed /v1/scale calls are queued and retried at next evaluation cycle. Multiple pending requests are coalesced into a single target cardinality.

Parameters:
- pending_action_queue: {cluster_id: latest_target_cardinality}
- evaluation_interval, max_retries

Returns:
Queue status: pending|executed|failed
```

### Scale-Up Policy

```
Description:
Monitor queue_depth from OpenNebula monitoring (frontend VM). When backlog > 0, calculate target_cardinality = min(current_cardinality + backlog, max_vms). Call /v1/scale with target_cardinality. If cluster at max_vms or marked saturated, route new devices to other clusters (migration deferred in MVP).

Key insight: Single device needs 1 VM (sequential execution). backlog = queue_depth indicates waiting devices/requests.

Parameters:
- evaluation_interval, max_vms (from CLUSTER template)

Returns:
Executes /v1/scale. Logs: {action: UP|NOOP, cluster_id, target_cardinality}
```

### Scale-Down Policy

```
Description:
When backlog (queue_depth) == 0 for K consecutive evaluation intervals, set target_cardinality = min_pool_size (1). Call /v1/scale with reduced target. The /v1/scale endpoint handles drain-first logic: idle VMs terminated immediately, busy VMs drained then terminated.

Parameters:
- min_pool_size (default: 1), K (consecutive zero-backlog intervals, e.g., 3)

Returns:
Logs: {action: DOWN, cluster_id, target_cardinality}
```

### Cluster Selection (Device-Cluster Allocation Optimizer)

```
Description:
Solves optimization problem to select best cluster for new device. Considers device requirements, cluster capacity, load distribution, CO2 policy. Operates at cluster level (which cluster for device). Complementary to OneDRS (which host within cluster for VM).

Interaction:
- Input: Device Scheduling/AppRequirements + cluster state snapshot
- Optimization: device-cluster compatibility, capacity constraints, load balance, CO2 minimization
- Output: cluster_id

Parameters:
- Scheduling (AppRequirements), cluster_capacity_headroom, policy_weights

Returns:
cluster_id
```

### Load Migration (Device Rebalancing)

```
Description:
Trigger migrations when cluster reaches max capacity. Use Device-Cluster Allocation Optimizer to move limited number of devices to clusters with headroom. Future: periodic sweep for proactive rebalancing.

Parameters:
- capacity_threshold, max_migrations_per_event

Returns:
{action: MIGRATE, moves: [{device_id, from_cluster, to_cluster}, ...]}
```

### Workload Optimization

```
Description:
Two-level optimization:
1. OneDRS: VM-level optimization within clusters (automatic, infrastructure-level)
2. Device-Cluster Optimizer: Device-level optimization between clusters (orchestrator-triggered, periodic)

Orchestrator monitors OneDRS results and triggers device migrations if single-cluster optimization insufficient.

Parameters:
- optimization_interval (device-level), ondrs_optimization_interval (VM-level, OneDRS config)

Returns:
Optional device migration hints
```

### Interfaces & Metrics

```
Description:
Monitoring: OpenNebula monitoring + CLUSTER templates
- queue_depth: from OpenNebula monitoring (frontend VM)
- current_cardinality: from OneFlow service info (onegate service show)
- max_vms, flavour: from CLUSTER template
Control: /v1/scale?cardinality=N per cluster (declarative, handles up/down)
Internal (used by /v1/scale): onegate service show/scale, onegate vm terminate --hard, serverless-runtime /control/stop-consuming

Parameters:
- opennebula_api_endpoint, scale_endpoint (/v1/scale per cluster), onegate_context (VM tokens)

Returns:
Telemetry and action results
```

### Anti-Flapping & Failure Handling

```
Description:
Prevent oscillations via:
- Pending action queue (coalesce multiple requests)
- Debouncing (aggregate metrics over time window)
- Retry with jitter for transient failures

Parameters:
- debounce_window, scale_request_timeout, retry_policy, max_pending_retries

Returns:
Operation result: success|failure with reason
```

---

## Glossary

- **backlog**: Equal to `queue_depth`; the number of pending requests in the frontend VM's queue (from OpenNebula monitoring)
- **target_cardinality**: The desired FINAL number of VMs in a cluster (not a delta); passed to `/v1/scale?cardinality=N`
- **saturated**: Cluster state flag (with TTL) set when scale-up refused due to capacity; during TTL, skip scaling and route new devices elsewhere
- **min_pool_size**: Minimum number of VMs to maintain per cluster (default: 1)
- **K**: Number of consecutive evaluation intervals with backlog==0 before triggering scale-down to min_pool_size
- **pending_action_queue**: Per-cluster queue holding latest target_cardinality during OneFlow cooldown; coalesced and retried
- **app_req_id**: OpenNebula application request ID for device; used as source-of-truth for cleanup (device disconnected if missing from ON DB)

---

## Key Design Decisions

- **Declarative Scaling**: Orchestrator calculates target_cardinality (FINAL number, not delta); /v1/scale handles execution complexity
- **Request-First Flow**: All device requests hit global endpoint; new devices trigger immediate cluster selection and scale-up
- **Device Stickiness**: Devices stay on assigned cluster unless orchestrator migrates (migrations deferred in MVP)
- **Capacity Enforcement**: Hard max_vms per cluster (from CLUSTER template); when full, route new devices to other clusters
- **Pending Action Queue**: No scale requests lost during OneFlow cooldown; coalesced and retried
- **Two-Level Optimization**: OneDRS (VM-to-host within cluster), Device-Cluster Optimizer (device-to-cluster assignment)
- **Graceful Scale-Down**: Drain-first via /v1/scale (idle immediate, busy after drain); triggered after K consecutive zero-backlog intervals
- **SQLite Concurrency**: Transactional locking prevents duplicate VM provisioning; cleanup via app_req_id check in ON DB
- **OpenNebula-Native Metrics**: queue_depth from ON monitoring, cardinality from OneFlow, max_vms from CLUSTER template (no external Prometheus dependency)

---

## Open Questions

1. **Optimizer Invocation Strategy**: Per-device calls (simple) vs batching (better optimization, higher latency)?
2. **Migration Cadence**: Capacity-triggered only initially; add periodic sweep later?
3. **Scale-Up Calculation**: Simple heuristic (current + queue_depth) vs forecast-based (remaining_time prediction)?
4. **Provision vs Wait Trade-off**: In some cases, provisioning a new VM may take longer than waiting for a busy VM to become idle. This will reduce the number of new VMs instantiated overall and therefore the occasions when clusters reach their max capacity. Implementing a robust estimator and decision logic for this trade-off increases complexity—should we keep it simple initially?
