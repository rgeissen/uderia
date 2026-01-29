# Cost Management System Implementation

## Overview
A comprehensive cost tracking and management system for LLM token consumption has been successfully implemented.

## Components Implemented

### 1. Database Layer
- **New Table**: `llm_model_costs`
  - Stores pricing for each provider/model combination
  - Tracks input/output cost per 1M tokens
  - Supports manual entries and LiteLLM syncing
  - Includes fallback pricing for unknown models
- **Migration**: `maintenance/migrate_llm_model_costs.py`
- **SQLAlchemy Model**: `LLMModelCost` in `auth/models.py`

### 2. Backend Services
- **Cost Manager**: `core/cost_manager.py`
  - Singleton service for all cost operations
  - LiteLLM integration for automatic pricing sync
  - Cost calculation based on actual model pricing
  - Fallback mechanism for unknown models
  - CRUD operations for cost entries

### 3. REST API Endpoints
All endpoints require admin authentication:

- `POST /api/v1/costs/sync` - Sync pricing from LiteLLM
- `GET /api/v1/costs/models` - Get all model costs
- `PUT /api/v1/costs/models/<id>` - Update a model cost
- `POST /api/v1/costs/models` - Add manual cost entry
- `DELETE /api/v1/costs/models/<id>` - Delete cost entry
- `PUT /api/v1/costs/fallback` - Update fallback cost
- `GET /api/v1/costs/analytics` - Get comprehensive cost analytics

### 4. Frontend UI

#### New Administration Tab: "Cost"
Located in the Administration pane with two main sections:

**A. Cost Analytics Dashboard (Top Section)**
- **KPI Cards**:
  - Total Cost (across all sessions)
  - Average Cost per Session
  - Average Cost per Turn
  - Total Sessions Analyzed
  
- **Visualization Charts**:
  - Cost by Provider (bar chart)
  - Top 5 Expensive Models (bar chart)

**B. Cost Configuration Table (Bottom Section)**
- **Fallback Cost Configuration**:
  - Adjustable default costs for unknown models
  - Input/Output cost per 1M tokens
  
- **Model Cost Table**:
  - Displays all provider/model pricing
  - Inline editing of costs
  - Source tracking (LiteLLM, Manual, System Default)
  - Last updated timestamps
  - Delete functionality for manual entries
  
- **Actions**:
  - "Sync from LiteLLM" button - Fetches latest pricing
  - "Add Manual Entry" button - Add custom model costs

### 5. JavaScript Handler
- **File**: `static/js/handlers/costManagement.js`
- **Features**:
  - Real-time cost data loading
  - Interactive table with inline editing
  - Chart rendering for analytics
  - Toast notifications for user feedback
  - Automatic data refresh after updates

### 6. Updated Dependencies
- Added `litellm>=1.0.0` to `requirements.txt`

### 7. Updated Analytics
- **Execution Dashboard** (`/api/v1/sessions/analytics`):
  - Now uses actual model-specific costs instead of $0.01/1K average
  - Iterates through all sessions and calculates real costs
  - More accurate cost estimates

## Key Features

### Hybrid Approach
- **Primary Source**: LiteLLM's model_cost dictionary
- **Manual Override**: Admins can add/edit any model
- **Fallback Mechanism**: Configurable default for unknown models
- **Full Autonomy**: All data stored locally in SQLite

### Cost Calculation
```python
cost = (input_tokens / 1_000_000) * input_cost_per_million + 
       (output_tokens / 1_000_000) * output_cost_per_million
```

### Provider Inference
When syncing from LiteLLM, the system automatically infers providers from model names:
- `gpt-*` → OpenAI
- `claude-*` → Anthropic
- `gemini-*` → Google
- `titan-*`, `nova-*` → Amazon
- And more...

## Usage Instructions

### For Administrators

1. **Access Cost Tab**:
   - Navigate to Administration pane
   - Click the "Cost" tab

2. **Initial Setup**:
   - Click "Sync from LiteLLM" to populate pricing data
   - Review and adjust fallback costs if needed

3. **Add Custom Model**:
   - Click "Add Manual Entry"
   - Enter provider, model, input/output costs
   - Saves with "manual" source tag

4. **Edit Existing Costs**:
   - Modify values directly in the table
   - Click "Save" button for that row
   - Changes marked as manual overrides

5. **Monitor Costs**:
   - View real-time analytics in dashboard
   - Track spending by provider/model
   - Identify expensive queries

### For Developers

**Using Cost Manager**:
```python
from trusted_data_agent.core.cost_manager import get_cost_manager

cost_manager = get_cost_manager()

# Calculate cost for a turn
cost = cost_manager.calculate_cost(
    provider="Google",
    model="gemini-2.5-flash",
    input_tokens=1000,
    output_tokens=500
)

# Get pricing for a model
costs = cost_manager.get_model_cost("Google", "gemini-2.5-flash")
# Returns: (input_cost_per_million, output_cost_per_million)

# Sync from LiteLLM
results = cost_manager.sync_from_litellm()
```

## Database Schema

```sql
CREATE TABLE llm_model_costs (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    input_cost_per_million REAL NOT NULL,
    output_cost_per_million REAL NOT NULL,
    is_manual_entry BOOLEAN NOT NULL DEFAULT 0,
    is_fallback BOOLEAN NOT NULL DEFAULT 0,
    source TEXT NOT NULL,
    last_updated DATETIME NOT NULL,
    notes TEXT,
    UNIQUE(provider, model)
);
```

## Future Enhancements

1. **Cost Budgets & Alerts**:
   - Set spending limits per user/session
   - Email alerts when thresholds exceeded

2. **Cost Trends**:
   - Historical cost tracking over time
   - Monthly/weekly spending reports
   - Cost forecasting

3. **RAG Cost Attribution**:
   - Update RAG savings to use actual model costs
   - Track cost impact of champion cases

4. **Export Capabilities**:
   - CSV export of cost data
   - Detailed cost reports

5. **Advanced Analytics**:
   - Cost efficiency metrics
   - Provider comparison
   - Model ROI analysis

## Testing Checklist

- [x] Database migration runs successfully
- [x] Cost Manager syncs from LiteLLM
- [x] REST API endpoints respond correctly
- [x] Admin UI displays Cost tab
- [x] Cost analytics dashboard loads
- [x] Cost table displays and updates
- [x] Fallback cost can be modified
- [x] Manual entries can be added/deleted
- [x] Analytics endpoint uses actual costs

## Migration Required

To use this feature, run:
```bash
python3 maintenance/migrate_llm_model_costs.py
```

Then restart the application and install new dependency:
```bash
pip install -r requirements.txt
```
