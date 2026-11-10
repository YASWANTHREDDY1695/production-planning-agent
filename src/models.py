from enum import Enum
from typing import List, Optional, Dict
from pydantic import BaseModel, Field


class WorkstationType(str, Enum):
    MB_PREP = "MB_PREP"                # Motherboard & CPU Mount
    CHASSIS = "CHASSIS"                # Chassis & PSU Mounting
    COMPONENT = "COMPONENT"            # GPU, RAM & Storage
    WIRING = "WIRING"                  # Cable Routing & Thermal
    BURNIN_TEST = "BURNIN_TEST"        # 24h/burn-in testing bench
    PACKAGING = "PACKAGING"            # Final QA & Box packaging


class Priority(str, Enum):
    LOW = "LOW"
    STANDARD = "STANDARD"
    HIGH = "HIGH"
    RUSH = "RUSH"                      # Urgent priority with heavy penalty if delayed


class TaskDefinition(BaseModel):
    task_id: str
    name: str
    workstation_type: WorkstationType
    duration_minutes: int
    predecessors: List[str] = Field(default_factory=list)


class ProductionOrder(BaseModel):
    order_id: str
    product_model: str                 # e.g., "Galleria XF-Titan", "Thirdwave Pro-Workstation"
    quantity: int = 1
    priority: Priority = Priority.STANDARD
    due_time_minutes: int              # Target completion time in minutes from shift start
    tasks: List[TaskDefinition] = Field(default_factory=list)


class Machine(BaseModel):
    machine_id: str
    name: str
    workstation_type: WorkstationType
    efficiency_multiplier: float = 1.0  # 1.0 = normal, 1.2 = faster, 0.8 = slower


class DowntimeWindow(BaseModel):
    machine_id: str
    start_minute: int
    end_minute: int
    reason: str = "Scheduled Maintenance or Breakdown"


class ScheduledTask(BaseModel):
    order_id: str
    task_id: str
    task_name: str
    machine_id: str
    start_minute: int
    end_minute: int
    duration_minutes: int
    workstation_type: str
    is_delayed: bool = False


class ScheduleMetrics(BaseModel):
    makespan_minutes: int              # Total time to finish all production orders
    total_orders: int
    delayed_orders: int
    machine_utilization_pct: Dict[str, float]
    solver_status: str
    solver_wall_time_seconds: float
    total_penalty_score: float


class ScheduleResponse(BaseModel):
    schedule: List[ScheduledTask]
    metrics: ScheduleMetrics
    downtimes_applied: List[DowntimeWindow] = Field(default_factory=list)
