# Template Workflow Test Plan

## Test Coverage

### 1. Template Card Rendering
- [ ] Navigate to RAG Maintenance → Planner Repository Constructors
- [ ] Verify all template cards display with correct icons and colors
- [ ] Verify each card shows Edit and Deploy buttons
- [ ] Verify "Ready" status badge appears on active templates

### 2. Card Click Behavior (Manual Entry)
- [ ] Click on a planner template card (not the buttons)
- [ ] Verify modal opens with Collection Name, MCP Server, Description fields
- [ ] Verify "Template Configuration" section shows manual entry fields
- [ ] Verify fields show: Database Name, MCP Tool Name, Examples (SQL Queries), MCP Context Prompt

**Expected**: Manual entry form for quick single-row addition

### 3. Edit Button Functionality
- [ ] Click Edit button on any template card
- [ ] Verify Edit modal opens with 3 tabs: Basic, Advanced, System Info
- [ ] Verify Basic tab shows template-specific parameters (e.g., Chunking Strategy for Knowledge, MCP Tool Name for SQL)
- [ ] Click Save → Verify success notification
- [ ] Click Cancel → Verify modal closes without saving

**Expected**: Template defaults editor with parameter customization

### 4. Deploy Button Functionality
- [ ] Click Deploy button on any template card
- [ ] Verify modal opens with 3-column layout:
  - **LEFT**: Configuration (Context Topic, Conversion Rules, Database Name, Num Examples, MCP Context Prompt)
  - **MIDDLE**: Generation Prompt (textarea with Refresh button)
  - **RIGHT**: Workflow (3 steps with numbered badges)
- [ ] Verify modal is wide (max-w-7xl)
- [ ] Verify all fields are populated if defaults were saved

**Expected**: 3-column LLM workflow for auto-generation

### 5. Edit Modal - Save/Reset
- [ ] Open Edit modal → Change parameters → Click Save
- [ ] Verify API call to `/api/v1/rag/templates/{id}/defaults` (POST)
- [ ] Verify success notification
- [ ] Reopen Edit modal → Verify changed values persist
- [ ] Click Reset → Confirm → Verify defaults removed
- [ ] Verify API call to `/api/v1/rag/templates/{id}/defaults` (DELETE)

**Expected**: Defaults stored per user per template

### 6. Deploy with Saved Defaults
- [ ] Edit template → Set custom defaults → Save
- [ ] Click Deploy button
- [ ] Verify Configuration fields pre-filled with saved values
- [ ] Verify Num Examples shows saved value
- [ ] Verify MCP Context Prompt shows saved value

**Expected**: Deploy pre-fills form with user's saved defaults

### 7. 3-Column Layout Verification
**Configuration Column (Left)**:
- [ ] Shows "Configuration" header with gear icon
- [ ] All input fields display vertically
- [ ] Info box at bottom: "Configure your generation parameters..."

**Prompt Column (Middle)**:
- [ ] Shows "Generation Prompt" header with document icon
- [ ] Refresh button in top-right
- [ ] Full-height textarea for prompt editing
- [ ] Help text: "You can edit this prompt before generation"

**Workflow Column (Right)**:
- [ ] Shows "Workflow" header with lightning icon
- [ ] Step 1 card: "Generate Context" (blue, numbered "1")
- [ ] Generate button in step 1
- [ ] Steps 2 and 3 initially hidden

### 8. Modal Width and Responsiveness
- [ ] Modal uses `max-w-7xl` (1280px)
- [ ] Grid displays 3 equal columns with `gap-6`
- [ ] No horizontal scroll needed
- [ ] All text readable, no truncation
- [ ] Buttons fit properly without wrapping

## Browser Compatibility
- [ ] Chrome/Edge (Chromium)
- [ ] Firefox
- [ ] Safari

## API Endpoints Used
- `GET /api/v1/rag/templates/list` - Template metadata
- `GET /api/v1/rag/templates/{id}/full` - Complete template manifest
- `GET /api/v1/rag/templates/{id}/defaults` - User defaults
- `POST /api/v1/rag/templates/{id}/defaults` - Save defaults
- `DELETE /api/v1/rag/templates/{id}/defaults` - Reset defaults

## Known Issues to Watch For
- ✓ Fixed: Deploy button showing manual entry instead of LLM workflow
- ✓ Fixed: Modal too narrow for 3-column layout
- ✓ Fixed: Population Method radio buttons removed (automated)
- ✓ Fixed: Card click authentication issues

## Success Criteria
✅ Template cards render correctly
✅ Card click → Manual entry form
✅ Edit button → Parameter editor
✅ Deploy button → 3-column LLM workflow
✅ Save/Reset defaults work correctly
✅ Deploy pre-fills saved defaults
✅ 3-column layout uses horizontal space effectively
✅ Modal is wide enough (max-w-7xl)

## Quick Verification Commands
```bash
# Check if server is running
curl -s http://localhost:5050/api/v1/rag/templates/list | jq '.templates | length'

# Get full template details
curl -s http://localhost:5050/api/v1/rag/templates/sql_query_v1/full | jq '.template.template_name'

# Check saved defaults (with auth token)
curl -s -H "Authorization: Bearer YOUR_TOKEN" http://localhost:5050/api/v1/rag/templates/sql_query_v1/defaults | jq '.'
```

## Pre-Test Checklist
- [x] Database migration completed (template_defaults table exists)
- [x] Backend API endpoints implemented with authentication
- [x] Frontend modal updated to max-w-7xl
- [x] 3-column grid layout implemented
- [x] Deploy button triggers LLM workflow
- [x] Card click triggers manual entry
- [x] Edit button opens parameter editor
- [x] Population Method section removed

## Ready to Test! 🚀
All systems are in place. Start with the basic card rendering test and work through each scenario.
