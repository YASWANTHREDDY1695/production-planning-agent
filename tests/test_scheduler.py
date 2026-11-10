import pytest
from src.models import (
    DowntimeWindow,
    Priority
)
from src.engine import ProductionSchedulingEngine
from src.simulator import ScenarioSimulator
from src.agent import ProductionAgent
from src.api import (
    health_check,
    get_factory_state,
    execute_agent_command,
    compute_schedule,
    ScheduleRequest,
    NaturalLanguageCommand
)


@pytest.fixture
def factory_setup():
    simulator = ScenarioSimulator()
    machines = simulator.machines
    orders = simulator.create_sample_pc_orders()
    engine = ProductionSchedulingEngine(machines)
    return {"simulator": simulator, "machines": machines, "orders": orders, "engine": engine}


def test_zero_machine_overlap(factory_setup):
    """Mathematical guarantee: No machine can execute more than one task simultaneously."""
    engine = factory_setup["engine"]
    orders = factory_setup["orders"]

    res = engine.solve(orders)
    assert res.metrics.solver_status in ("OPTIMAL", "FEASIBLE")

    # Group tasks by assigned machine
    tasks_by_machine = {}
    for task in res.schedule:
        tasks_by_machine.setdefault(task.machine_id, []).append(task)

    for machine_id, task_list in tasks_by_machine.items():
        # Sort by start minute
        sorted_tasks = sorted(task_list, key=lambda x: x.start_minute)
        for i in range(len(sorted_tasks) - 1):
            curr_task = sorted_tasks[i]
            next_task = sorted_tasks[i + 1]
            assert curr_task.end_minute <= next_task.start_minute, (
                f"Overlap detected on machine {machine_id}! "
                f"Task {curr_task.task_id} ends at {curr_task.end_minute}, "
                f"but {next_task.task_id} starts at {next_task.start_minute}"
            )


def test_strict_precedence_satisfaction(factory_setup):
    """Predecessor constraint: Task N must completely finish before Task N+1 starts."""
    engine = factory_setup["engine"]
    orders = factory_setup["orders"]

    res = engine.solve(orders)
    task_map = {(t.order_id, t.task_id): t for t in res.schedule}

    for order in orders:
        for task in order.tasks:
            curr_scheduled = task_map[(order.order_id, task.task_id)]
            for pred_id in task.predecessors:
                pred_scheduled = task_map[(order.order_id, pred_id)]
                assert curr_scheduled.start_minute >= pred_scheduled.end_minute, (
                    f"Precedence violation in {order.order_id}! "
                    f"Task {task.task_id} started at {curr_scheduled.start_minute} "
                    f"before predecessor {pred_id} finished at {pred_scheduled.end_minute}"
                )


def test_downtime_avoidance(factory_setup):
    """Guaranteed avoidance: Machines under maintenance must NOT be assigned any work."""
    engine = factory_setup["engine"]
    orders = factory_setup["orders"]

    # Introduce a 120-minute downtime on CP-01 (GPU bay)
    dt = DowntimeWindow(machine_id="CP-01", start_minute=30, end_minute=150, reason="Motor Failure")
    res = engine.solve(orders, downtimes=[dt])

    for task in res.schedule:
        if task.machine_id == "CP-01":
            # Must either end before downtime starts OR start after downtime ends
            overlap = not (task.end_minute <= dt.start_minute or task.start_minute >= dt.end_minute)
            assert not overlap, (
                f"Task {task.task_id} was scheduled on CP-01 during downtime! "
                f"Task: [{task.start_minute}, {task.end_minute}], Downtime: [{dt.start_minute}, {dt.end_minute}]"
            )


def test_agent_intent_parsing(factory_setup):
    """Verify that natural language commands are translated cleanly to structured constraints."""
    agent = ProductionAgent()
    orders = factory_setup["orders"]

    prompt = "Machine CP-01 down from 60 to 180 and rush order ORD-103"
    intent = agent.parse_operator_instruction(prompt, orders)

    assert len(intent.downtimes_to_add) == 1
    assert intent.downtimes_to_add[0].machine_id == "CP-01"
    assert intent.downtimes_to_add[0].start_minute == 60
    assert intent.downtimes_to_add[0].end_minute == 180
    assert intent.priority_updates.get("ORD-103") == Priority.RUSH


def test_api_handlers():
    """Verify all FastAPI routes and logic respond cleanly."""
    # Health check
    health = health_check()
    assert health["status"] == "healthy"
    assert health["machines_active"] == 12

    # Factory state
    state = get_factory_state()
    assert len(state["machines"]) == 12
    assert len(state["orders"]) >= 5

    # Schedule compute
    sched = compute_schedule(ScheduleRequest())
    assert sched.metrics.solver_status in ("OPTIMAL", "FEASIBLE")
    assert sched.metrics.makespan_minutes > 0

    # Agent NL command execution
    cmd_res = execute_agent_command(NaturalLanguageCommand(command="Machine MB-02 down from 50 to 120 and rush ORD-103"))
    assert "solution" in cmd_res
    assert cmd_res["solution"].metrics.makespan_minutes > 0
    assert len(cmd_res["intent_parsed"].downtimes_to_add) == 1
