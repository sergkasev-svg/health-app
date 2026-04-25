from __future__ import annotations

# Re-export canonical implementation from services layer
# so orchestrator can import from app.branches.* without logic duplication.
from app.services.zaz_food_branch_integration import (  # noqa: F401
    FoodBranchInput,
    FoodBranchOutput,
    FoodBranchRelevanceFilter,
    ZaZFoodBranchIntegration,
    ZaZFoodOrchestratorAdapter,
)

