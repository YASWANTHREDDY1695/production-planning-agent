from typing import List, Dict, Any
from src.models import (
    ProductionOrder,
    Machine,
    DowntimeWindow,
    WorkstationType,
    Priority,
    TaskDefinition,
    ScheduleResponse
)
from src.engine import ProductionSchedulingEngine





class ScenarioSimulator:
    """
    Simulation engine to perform 'What-If' operational analysis.
    Computes delta impacts on makespan, bottlenecks, and delivery risk.
    """

    def __init__(self, default_machines: List[Machine] = None):
        self.machines = default_machines or self.get_default_factory_machines()
        self.engine = ProductionSchedulingEngine(self.machines)

    @staticmethod
    def get_default_factory_machines() -> List[Machine]:
        """
        Thirdwave Assembly Line Topology:
        - 2 Motherboard & CPU prep stations
        - 2 Chassis & PSU mounting stations
        - 2 GPU & Component insertion stations
        - 1 Precision cable management & thermal bench
        - 3 Automated QA & Burn-in stress test racks
        - 2 Final inspection & packaging bays
        """
        return [
            Machine(machine_id="MB-01", name="Motherboard Prep Bay 1", workstation_type=WorkstationType.MB_PREP, efficiency_multiplier=1.0),
            Machine(machine_id="MB-02", name="Motherboard Prep Bay 2", workstation_type=WorkstationType.MB_PREP, efficiency_multiplier=1.1),
            Machine(machine_id="CH-01", name="Chassis Mount Bay 1", workstation_type=WorkstationType.CHASSIS, efficiency_multiplier=1.0),
            Machine(machine_id="CH-02", name="Chassis Mount Bay 2", workstation_type=WorkstationType.CHASSIS, efficiency_multiplier=0.95),
            Machine(machine_id="CP-01", name="GPU & Component Station 1", workstation_type=WorkstationType.COMPONENT, efficiency_multiplier=1.0),
            Machine(machine_id="CP-02", name="GPU & Component Station 2", workstation_type=WorkstationType.COMPONENT, efficiency_multiplier=1.15),
            Machine(machine_id="WR-01", name="Wiring & Thermal Station 1", workstation_type=WorkstationType.WIRING, efficiency_multiplier=1.0),
            Machine(machine_id="QA-01", name="Burn-In Stress Bench 1", workstation_type=WorkstationType.BURNIN_TEST, efficiency_multiplier=1.0),
            Machine(machine_id="QA-02", name="Burn-In Stress Bench 2", workstation_type=WorkstationType.BURNIN_TEST, efficiency_multiplier=1.0),
            Machine(machine_id="QA-03", name="Burn-In Stress Bench 3", workstation_type=WorkstationType.BURNIN_TEST, efficiency_multiplier=1.0),
            Machine(machine_id="PK-01", name="Packaging Bay 1", workstation_type=WorkstationType.PACKAGING, efficiency_multiplier=1.0),
            Machine(machine_id="PK-02", name="Packaging Bay 2", workstation_type=WorkstationType.PACKAGING, efficiency_multiplier=1.05),
        ]

    @staticmethod
    def create_sample_pc_orders() -> List[ProductionOrder]:
        """
        Creates realistic BTO (Build-to-Order) PC orders representing
        different models (Galleria Gaming PC, Office Pro, AI Workstation).
        """
        def make_pc_tasks(prefix: str, prep_m: int, chas_m: int, comp_m: int, wire_m: int, test_m: int, pack_m: int) -> List[TaskDefinition]:
            return [
                TaskDefinition(task_id=f"{prefix}_t1", name="MB & CPU Mount", workstation_type=WorkstationType.MB_PREP, duration_minutes=prep_m),
                TaskDefinition(task_id=f"{prefix}_t2", name="Chassis Assembly", workstation_type=WorkstationType.CHASSIS, duration_minutes=chas_m, predecessors=[f"{prefix}_t1"]),
                TaskDefinition(task_id=f"{prefix}_t3", name="GPU & RAM Install", workstation_type=WorkstationType.COMPONENT, duration_minutes=comp_m, predecessors=[f"{prefix}_t2"]),
                TaskDefinition(task_id=f"{prefix}_t4", name="Thermal & Wiring", workstation_type=WorkstationType.WIRING, duration_minutes=wire_m, predecessors=[f"{prefix}_t3"]),
                TaskDefinition(task_id=f"{prefix}_t5", name="Burn-In Stress QA", workstation_type=WorkstationType.BURNIN_TEST, duration_minutes=test_m, predecessors=[f"{prefix}_t4"]),
                TaskDefinition(task_id=f"{prefix}_t6", name="Packaging & Labeling", workstation_type=WorkstationType.PACKAGING, duration_minutes=pack_m, predecessors=[f"{prefix}_t5"]),
            ]

        return [
            ProductionOrder(
                order_id="ORD-101",
                product_model="Galleria Gaming XF-Titan",
                quantity=1,
                priority=Priority.HIGH,
                due_time_minutes=240,
                tasks=make_pc_tasks("ord101", prep_m=25, chas_m=30, comp_m=35, wire_m=20, test_m=60, pack_m=15)
            ),
            ProductionOrder(
                order_id="ORD-102",
                product_model="Thirdwave Pro AI-Workstation",
                quantity=1,
                priority=Priority.RUSH,
                due_time_minutes=300,
                tasks=make_pc_tasks("ord102", prep_m=35, chas_m=40, comp_m=50, wire_m=30, test_m=90, pack_m=20)
            ),
            ProductionOrder(
                order_id="ORD-103",
                product_model="Raytrek Design Studio PC",
                quantity=1,
                priority=Priority.STANDARD,
                due_time_minutes=360,
                tasks=make_pc_tasks("ord103", prep_m=20, chas_m=25, comp_m=30, wire_m=15, test_m=45, pack_m=15)
            ),
            ProductionOrder(
                order_id="ORD-104",
                product_model="Monarch Slim Enterprise",
                quantity=1,
                priority=Priority.STANDARD,
                due_time_minutes=420,
                tasks=make_pc_tasks("ord104", prep_m=15, chas_m=20, comp_m=20, wire_m=15, test_m=30, pack_m=10)
            ),
            ProductionOrder(
                order_id="ORD-105",
                product_model="Galleria Esports Edition",
                quantity=1,
                priority=Priority.HIGH,
                due_time_minutes=320,
                tasks=make_pc_tasks("ord105", prep_m=25, chas_m=30, comp_m=35, wire_m=20, test_m=60, pack_m=15)
            ),
        ]

    def run_comparison(
        self,
        orders: List[ProductionOrder],
        baseline_downtimes: List[DowntimeWindow],
        simulated_downtimes: List[DowntimeWindow]
    ) -> Dict[str, Any]:
        """Runs baseline vs disrupted scenario and computes key differences."""
        baseline_res = self.engine.solve(orders, baseline_downtimes)
        simulated_res = self.engine.solve(orders, simulated_downtimes)

        makespan_delta = simulated_res.metrics.makespan_minutes - baseline_res.metrics.makespan_minutes
        delayed_delta = simulated_res.metrics.delayed_orders - baseline_res.metrics.delayed_orders

        return {
            "baseline": baseline_res,
            "simulated": simulated_res,
            "impact_summary": {
                "makespan_delta_minutes": makespan_delta,
                "delayed_orders_delta": delayed_delta,
                "makespan_increase_pct": round((makespan_delta / max(1, baseline_res.metrics.makespan_minutes)) * 100, 2),
                "is_critical_delay": delayed_delta > 0 or makespan_delta > 60
            }
        }
