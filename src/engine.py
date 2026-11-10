import time
from typing import List, Dict, Tuple
from ortools.sat.python import cp_model

from src.models import (
    ProductionOrder,
    Machine,
    DowntimeWindow,
    ScheduledTask,
    ScheduleMetrics,
    ScheduleResponse,
    Priority
)


class ProductionSchedulingEngine:
    """
    Deterministic Job Shop / Flexible Job Shop Scheduling (FJSP) engine
    using Google OR-Tools CP-SAT (Constraint Programming - Satisfiability).
    Guarantees:
      1. Zero machine overlap (no machine handles 2 jobs simultaneously)
      2. Strict precedence satisfaction (task n finishes before task n+1 starts)
      3. Guaranteed downtime avoidance (machines in maintenance take no tasks)
      4. Multi-objective optimization (minimizing makespan + weighted tardiness)
    """

    def __init__(self, machines: List[Machine]):
        self.machines = machines
        self.machines_by_id = {m.machine_id: m for m in machines}
        self.machines_by_type: Dict[str, List[Machine]] = {}
        for m in machines:
            self.machines_by_type.setdefault(m.workstation_type.value, []).append(m)

    def solve(
        self,
        orders: List[ProductionOrder],
        downtimes: List[DowntimeWindow] = None,
        max_time_seconds: float = 10.0
    ) -> ScheduleResponse:
        downtimes = downtimes or []
        model = cp_model.CpModel()

        # Upper bound horizon estimate (sum of all task durations)
        total_duration = sum(
            t.duration_minutes for order in orders for t in order.tasks
        ) + sum(d.end_minute for d in downtimes) + 2000
        horizon = max(2880, total_duration)  # At least 48 hours in minutes

        # Data structures to store variables
        all_tasks: Dict[Tuple[str, str], Dict] = {}
        machine_to_intervals: Dict[str, List[cp_model.IntervalVar]] = {
            m.machine_id: [] for m in self.machines
        }
        order_ends: Dict[str, cp_model.IntVar] = {}

        # 1. Enforce Downtimes as fixed interval variables on machines
        for idx, dt in enumerate(downtimes):
            if dt.machine_id in machine_to_intervals:
                dt_duration = max(1, dt.end_minute - dt.start_minute)
                dt_interval = model.NewIntervalVar(
                    dt.start_minute,
                    dt_duration,
                    dt.end_minute,
                    f"downtime_{dt.machine_id}_{idx}"
                )
                machine_to_intervals[dt.machine_id].append(dt_interval)

        # 2. Build task intervals across candidate machines
        for order in orders:
            task_dict_for_order = {}
            for task in order.tasks:
                compatible_machines = self.machines_by_type.get(
                    task.workstation_type.value, []
                )
                if not compatible_machines:
                    raise ValueError(
                        f"No available machine configured for workstation type: {task.workstation_type}"
                    )

                start_var = model.NewIntVar(0, horizon, f"start_{order.order_id}_{task.task_id}")
                end_var = model.NewIntVar(0, horizon, f"end_{order.order_id}_{task.task_id}")

                # Optional intervals for each compatible machine
                optional_intervals = []
                presence_vars = []

                for m in compatible_machines:
                    # Calculate duration adjusted for machine efficiency
                    effective_duration = max(
                        1, int(round(task.duration_minutes / m.efficiency_multiplier))
                    )
                    pres_var = model.NewBoolVar(
                        f"pres_{order.order_id}_{task.task_id}_{m.machine_id}"
                    )
                    presence_vars.append(pres_var)

                    opt_interval = model.NewOptionalIntervalVar(
                        start_var,
                        effective_duration,
                        end_var,
                        pres_var,
                        f"opt_{order.order_id}_{task.task_id}_{m.machine_id}"
                    )
                    optional_intervals.append(opt_interval)
                    machine_to_intervals[m.machine_id].append(opt_interval)

                # Exactly one machine must be selected for this task
                model.AddExactlyOne(presence_vars)

                task_dict_for_order[task.task_id] = {
                    "start": start_var,
                    "end": end_var,
                    "presence_vars": dict(zip([m.machine_id for m in compatible_machines], presence_vars)),
                    "duration": task.duration_minutes,
                    "workstation_type": task.workstation_type.value,
                    "name": task.name
                }

            all_tasks[order.order_id] = task_dict_for_order

            # Precedence constraints within order
            for task in order.tasks:
                for pred_id in task.predecessors:
                    if pred_id in task_dict_for_order:
                        # Successor task start >= Predecessor task end
                        model.Add(
                            task_dict_for_order[task.task_id]["start"] >=
                            task_dict_for_order[pred_id]["end"]
                        )

            # Order completion variable (max end of its tasks)
            order_end = model.NewIntVar(0, horizon, f"order_end_{order.order_id}")
            task_ends = [t["end"] for t in task_dict_for_order.values()]
            if task_ends:
                model.AddMaxEquality(order_end, task_ends)
                order_ends[order.order_id] = order_end

        # 3. Disjunctive resource constraints: No two tasks overlap on the same machine
        for machine_id, intervals in machine_to_intervals.items():
            if intervals:
                model.AddNoOverlap(intervals)

        # 4. Objective Function: Minimize Makespan + Weighted Tardiness
        makespan = model.NewIntVar(0, horizon, "makespan")
        if order_ends:
            model.AddMaxEquality(makespan, list(order_ends.values()))

        # Priority weights
        priority_weights = {
            Priority.RUSH: 100,
            Priority.HIGH: 30,
            Priority.STANDARD: 10,
            Priority.LOW: 2
        }

        penalties = []
        for order in orders:
            weight = priority_weights.get(order.priority, 10)
            tardiness = model.NewIntVar(0, horizon, f"tardiness_{order.order_id}")
            # tardiness >= order_end - due_time
            model.Add(tardiness >= order_ends[order.order_id] - order.due_time_minutes)
            penalties.append(weight * tardiness)

        # Multi-objective: 2 * makespan + sum(penalties)
        model.Minimize(2 * makespan + sum(penalties))

        # Solve
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = max_time_seconds
        solver.parameters.num_workers = 4

        start_solve_time = time.time()
        status = solver.Solve(model)
        solve_duration = time.time() - start_solve_time

        status_str = solver.StatusName(status)

        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError(f"Solver failed to find a valid schedule. Status: {status_str}")

        # Extract Results
        scheduled_tasks: List[ScheduledTask] = []
        machine_busy_minutes: Dict[str, int] = {m.machine_id: 0 for m in self.machines}
        delayed_orders_count = 0
        total_penalty = 0.0

        for order in orders:
            order_finished_minute = solver.Value(order_ends[order.order_id])
            is_order_late = order_finished_minute > order.due_time_minutes
            if is_order_late:
                delayed_orders_count += 1
                penalty_val = (order_finished_minute - order.due_time_minutes) * priority_weights.get(order.priority, 10)
                total_penalty += penalty_val

            for task in order.tasks:
                task_data = all_tasks[order.order_id][task.task_id]
                start_val = solver.Value(task_data["start"])
                end_val = solver.Value(task_data["end"])

                assigned_machine_id = None
                for m_id, pres_var in task_data["presence_vars"].items():
                    if solver.Value(pres_var) == 1:
                        assigned_machine_id = m_id
                        break

                if assigned_machine_id:
                    duration = end_val - start_val
                    machine_busy_minutes[assigned_machine_id] += duration

                    scheduled_tasks.append(
                        ScheduledTask(
                            order_id=order.order_id,
                            task_id=task.task_id,
                            task_name=task_data["name"],
                            machine_id=assigned_machine_id,
                            start_minute=start_val,
                            end_minute=end_val,
                            duration_minutes=duration,
                            workstation_type=task_data["workstation_type"],
                            is_delayed=is_order_late
                        )
                    )

        # Sort tasks by start time
        scheduled_tasks.sort(key=lambda x: (x.start_minute, x.machine_id))

        final_makespan = solver.Value(makespan) if order_ends else 0

        # Calculate Machine Utilization %
        utilization: Dict[str, float] = {}
        for m in self.machines:
            if final_makespan > 0:
                util = round((machine_busy_minutes[m.machine_id] / final_makespan) * 100, 2)
            else:
                util = 0.0
            utilization[m.machine_id] = min(100.0, util)

        metrics = ScheduleMetrics(
            makespan_minutes=final_makespan,
            total_orders=len(orders),
            delayed_orders=delayed_orders_count,
            machine_utilization_pct=utilization,
            solver_status=status_str,
            solver_wall_time_seconds=round(solve_duration, 4),
            total_penalty_score=total_penalty
        )

        return ScheduleResponse(
            schedule=scheduled_tasks,
            metrics=metrics,
            downtimes_applied=downtimes
        )
