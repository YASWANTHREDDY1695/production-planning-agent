import os
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from src.models import (
    ProductionOrder,
    Machine,
    DowntimeWindow,
    ScheduleResponse
)
from src.engine import ProductionSchedulingEngine
from src.simulator import ScenarioSimulator
from src.agent import ProductionAgent

app = FastAPI(
    title="Thirdwave Autonomous Production Planning & Dispatching Agent",
    description="Deterministic Job Shop Scheduling (OR-Tools) + LLM Agent Layer for Hardware Assembly Lines",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory factory state
simulator = ScenarioSimulator()
default_machines = simulator.machines
default_orders = simulator.create_sample_pc_orders()
active_downtimes: List[DowntimeWindow] = []
agent = ProductionAgent()


class ScheduleRequest(BaseModel):
    orders: Optional[List[ProductionOrder]] = None
    downtimes: Optional[List[DowntimeWindow]] = None


class WhatIfRequest(BaseModel):
    machine_id: str
    downtime_start: int
    downtime_end: int
    rush_order_id: Optional[str] = None


class NaturalLanguageCommand(BaseModel):
    command: str


@app.get("/api/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Production Planning & Dispatching Agent",
        "solver": "Google OR-Tools CP-SAT (v9.15)",
        "machines_active": len(default_machines),
        "target_assembly": "Thirdwave High-Performance PC & Workstation Assembly"
    }


@app.get("/api/factory/state")
def get_factory_state():
    return {
        "machines": default_machines,
        "orders": default_orders,
        "active_downtimes": active_downtimes
    }


@app.post("/api/schedule", response_model=ScheduleResponse)
def compute_schedule(request: ScheduleRequest):
    orders = request.orders or default_orders
    downtimes = request.downtimes if request.downtimes is not None else active_downtimes
    try:
        engine = ProductionSchedulingEngine(default_machines)
        return engine.solve(orders, downtimes)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/simulate/whatif")
def simulate_scenario(request: WhatIfRequest):
    try:
        simulated_downtimes = list(active_downtimes)
        simulated_downtimes.append(
            DowntimeWindow(
                machine_id=request.machine_id,
                start_minute=request.downtime_start,
                end_minute=request.downtime_end,
                reason="Simulated What-If Disruption"
            )
        )

        orders_to_run = [o.model_copy(deep=True) for o in default_orders]
        if request.rush_order_id:
            for o in orders_to_run:
                if o.order_id.upper() == request.rush_order_id.upper():
                    from src.models import Priority
                    o.priority = Priority.RUSH

        result = simulator.run_comparison(
            orders=orders_to_run,
            baseline_downtimes=active_downtimes,
            simulated_downtimes=simulated_downtimes
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/agent/command")
def execute_agent_command(nl_cmd: NaturalLanguageCommand):
    try:
        # 1. Parse intent using the Agent
        intent = agent.parse_operator_instruction(nl_cmd.command, default_orders)

        # 2. Apply updates
        orders_to_run = [o.model_copy(deep=True) for o in default_orders]
        for o in orders_to_run:
            if o.order_id in intent.priority_updates:
                o.priority = intent.priority_updates[o.order_id]
            if o.order_id in intent.deadline_updates:
                o.due_time_minutes = intent.deadline_updates[o.order_id]

        new_downtimes = list(active_downtimes) + intent.downtimes_to_add

        # 3. Re-solve schedule mathematically with zero hallucinations
        engine = ProductionSchedulingEngine(default_machines)
        solution = engine.solve(orders_to_run, new_downtimes)

        return {
            "intent_parsed": intent,
            "solution": solution,
            "message": f"Successfully processed instruction: '{nl_cmd.command}'"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    if os.path.exists(dashboard_path):
        with open(dashboard_path, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Production Planning Agent API running. Visit /docs for Swagger API.</h1>"
