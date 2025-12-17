Perfect! Much simpler. Here's the **updated logical flow without CPU sorting**:

---

## Scale-Down Logical Flow (Simplified - No CPU Sorting)

### **Phase 1: Identify VMs to Remove**

1. Get current service info from onegate
2. Extract all FaaS VMs from service
3. Calculate: `vms_to_remove = current_cardinality - target_cardinality`

---

### **Phase 2: Classify ALL VMs (Idle vs Busy)**

For each VM in the FaaS role:

4. Fetch Prometheus metrics from `http://{vm_ip}:9100/metrics`
5. Parse single metric: vm_is_executing
6. Check value:
 - vm_is_executing 1 → VM is BUSY (add to busy_vms)
 - vm_is_executing 0 → VM is IDLE (add to idle_vms)

---

### **Phase 3: Terminate Idle VMs First**

7. Select VMs to terminate from `idle_vms` (up to `vms_to_remove`)
8. For each selected idle VM:
   - Log: "VM {id} is idle, terminating immediately"
   - Terminate VM
   - Decrement `vms_to_remove` counter

9. **If `vms_to_remove == 0`** → **DONE**, return success

---

### **Phase 4: Unbind Busy VMs (If More Removals Needed)**

10. Calculate: `remaining = vms_to_remove` (how many more to remove)
11. Select first N VMs from `busy_vms` where N = remaining
12. For each selected busy VM:
    - Log: "VM {id} is busy, stopping consumer"
    - POST to `http://{vm_ip}:8000/control/stop-consuming`
    - Add VM to `waiting_for_idle` list

---

### **Phase 5: Poll Until Busy VMs Finish Execution**

13. Start timeout timer (e.g., 10 minutes)
14. While `waiting_for_idle` is NOT empty AND timeout not reached:
    
    15. For each VM in `waiting_for_idle`:
        - Fetch Prometheus metrics from `http://{vm_ip}:9100/metrics`
        - Sum all `vm_current_function` values
        
        16. **If sum == 0** (finished execution):
            - Log: "VM {id} finished execution, now idle"
            - Remove from `waiting_for_idle`
            - Add to `ready_to_terminate`
    
    17. Sleep 5 seconds (polling interval)

---

### **Phase 6: Terminate Now-Idle VMs**

For each VM in `ready_to_terminate`:

18. Log: "Terminating VM {id}"
19. Terminate VM

---

### **Phase 7: Handle Timeout (Force Termination)**

20. If timeout reached AND `waiting_for_idle` still has VMs:
    - Log WARNING: "X VMs did not finish within timeout, force terminating"
    - For each VM: terminate anyway

---

### **Phase 8: Final Verification & Return**

21. Poll oneflow until `current_cardinality == target_cardinality`
22. Return response with statistics

---

## 📊 Example Walkthrough (Simplified)

**Scenario**: Scale from 5 VMs → 2 VMs (remove 3 VMs)

```
Initial state (any order):
  VM_810: vm_current_function sum = 0  → IDLE
  VM_811: vm_current_function sum = 1  → BUSY
  VM_812: vm_current_function sum = 0  → IDLE
  VM_813: vm_current_function sum = 1  → BUSY
  VM_814: vm_current_function sum = 0  → IDLE

Classification:
  idle_vms:  [810, 812, 814]  → 3 idle VMs
  busy_vms:  [811, 813]       → 2 busy VMs
  
Need to remove: 3 VMs

Phase 3: Terminate idle VMs
  We need 3, we have 3 idle → Perfect!
  ✅ Terminate VM_810
  ✅ Terminate VM_812
  ✅ Terminate VM_814
  
  vms_to_remove = 0 → DONE! ✅

Alternative scenario: Only 2 idle VMs available

  idle_vms:  [810, 812]       → 2 idle VMs
  busy_vms:  [811, 813, 814]  → 3 busy VMs
  
  Need to remove: 3 VMs

Phase 3: Terminate 2 idle VMs
  ✅ Terminate VM_810
  ✅ Terminate VM_812
  vms_to_remove = 1 (still need 1 more)

Phase 4: Unbind 1 busy VM (pick any, e.g., VM_811)
  ⏸️  POST http://vm_811_ip:8000/control/stop-consuming
  waiting_for_idle: [811]

Phase 5: Poll VM_811
  t=0s:  sum = 1 (busy)
  t=5s:  sum = 1 (busy)
  t=10s: sum = 0 (idle!) ✅
  ready_to_terminate: [811]

Phase 6: Terminate
  ✅ Terminate VM_811

Result: Final cardinality = 2
```
