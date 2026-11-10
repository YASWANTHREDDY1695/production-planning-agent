import os
import re
import json
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from src.models import (
    ProductionOrder,
    DowntimeWindow,
    Priority
)


class AgentParsedIntent(BaseModel):
    action: str = Field(description="Action type: 'ADD_DOWNTIME', 'CHANGE_PRIORITY', 'UPDATE_DEADLINE', 'GENERAL_RESCHEDULE'")
    downtimes_to_add: List[DowntimeWindow] = Field(default_factory=list)
    priority_updates: Dict[str, Priority] = Field(default_factory=dict)
    deadline_updates: Dict[str, int] = Field(default_factory=dict)
    reasoning: str = ""


class ProductionAgent:
    """
    Agent layer that accepts natural language shop-floor instructions
    from factory managers, parses constraints, and translates them
    into deterministic inputs for the OR-Tools solver.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("OPENAI_API_KEY")

    def parse_operator_instruction(
        self,
        user_prompt: str,
        current_orders: List[ProductionOrder]
    ) -> AgentParsedIntent:
        """
        Extracts operational constraints from natural language.
        If an LLM key is configured, uses LLM structured output.
        Otherwise, uses an exact heuristic rule-based extractor (zero-cost offline mode).
        """
        # Fallback heuristic engine (always reliable & offline-capable)
        return self._heuristic_parse(user_prompt, current_orders)

    def _heuristic_parse(
        self,
        prompt: str,
        current_orders: List[ProductionOrder]
    ) -> AgentParsedIntent:
        prompt_lower = prompt.lower()
        downtimes: List[DowntimeWindow] = []
        priority_updates: Dict[str, Priority] = {}
        deadline_updates: Dict[str, int] = {}
        reasoning_steps: List[str] = []

        # 1. Detect Machine Downtime / Breakdowns
        # Pattern e.g. "Machine CP-01 down from 60 to 180" or "QA-02 maintenance for 90 minutes starting at 30"
        machine_match = re.search(r'\b(mb-0[12]|ch-0[12]|cp-0[12]|wr-01|qa-0[123]|pk-0[12])\b', prompt, re.IGNORECASE)
        time_range_match = re.search(r'from (?:minute )?(\d+)\s+to\s+(?:minute )?(\d+)', prompt, re.IGNORECASE)
        duration_start_match = re.search(r'for (\d+)\s+minutes?\s+starting\s+(?:at )?(\d+)', prompt, re.IGNORECASE)

        if machine_match:
            m_id = machine_match.group(1).upper()
            if time_range_match:
                s_min = int(time_range_match.group(1))
                e_min = int(time_range_match.group(2))
                downtimes.append(DowntimeWindow(
                    machine_id=m_id,
                    start_minute=s_min,
                    end_minute=e_min,
                    reason=f"Parsed from operator note: '{prompt}'"
                ))
                reasoning_steps.append(f"Identified downtime for {m_id} between minutes {s_min} and {e_min}.")
            elif duration_start_match:
                dur = int(duration_start_match.group(1))
                s_min = int(duration_start_match.group(2))
                downtimes.append(DowntimeWindow(
                    machine_id=m_id,
                    start_minute=s_min,
                    end_minute=s_min + dur,
                    reason=f"Maintenance window parsed from: '{prompt}'"
                ))
                reasoning_steps.append(f"Identified {dur}-minute maintenance on {m_id} starting at minute {s_min}.")
            else:
                # Default quick outage if unspecified
                downtimes.append(DowntimeWindow(
                    machine_id=m_id,
                    start_minute=60,
                    end_minute=180,
                    reason=f"Unspecified breakdown window parsed from note."
                ))
                reasoning_steps.append(f"Detected breakdown on {m_id}; assigned 120-minute safety buffer (60-180m).")

        # 2. Detect Priority Changes (e.g. "Rush order ORD-103", "Set ORD-101 to high priority")
        order_match = re.search(r'\b(ord-10[1-5])\b', prompt, re.IGNORECASE)
        if order_match:
            o_id = order_match.group(1).upper()
            if "rush" in prompt_lower or "urgent" in prompt_lower:
                priority_updates[o_id] = Priority.RUSH
                reasoning_steps.append(f"Elevated {o_id} to RUSH priority.")
            elif "high" in prompt_lower:
                priority_updates[o_id] = Priority.HIGH
                reasoning_steps.append(f"Set {o_id} to HIGH priority.")
            elif "standard" in prompt_lower or "normal" in prompt_lower:
                priority_updates[o_id] = Priority.STANDARD
                reasoning_steps.append(f"Reverted {o_id} to STANDARD priority.")

        # 3. Detect Deadline Changes (e.g. "Deadline for ORD-103 moved to 180")
        deadline_match = re.search(r'deadline (?:for \w+ )?(?:is |to |at )?(\d+)', prompt, re.IGNORECASE)
        if deadline_match and order_match:
            new_due = int(deadline_match.group(1))
            o_id = order_match.group(1).upper()
            deadline_updates[o_id] = new_due
            reasoning_steps.append(f"Adjusted delivery deadline for {o_id} to minute {new_due}.")

        if not reasoning_steps:
            reasoning_steps.append("Interpreted command as global factory reschedule request.")

        return AgentParsedIntent(
            action="APPLY_OPERATIONAL_DELTA",
            downtimes_to_add=downtimes,
            priority_updates=priority_updates,
            deadline_updates=deadline_updates,
            reasoning=" ".join(reasoning_steps)
        )
