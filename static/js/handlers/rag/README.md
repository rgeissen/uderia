# RAG Collection Management - Module Structure

## Overview
The RAG Collection Management system has been refactored from a monolithic 3000+ line file into modular, maintainable components.

## Module Structure

```
static/js/handlers/
├── ragCollectionManagement.js     # Main coordinator (~300 lines)
└── rag/
    ├── utils.js                   # Pure utility functions
    ├── templateSystem.js          # Template loading & rendering
    ├── populationWorkflow.js      # 2-level population flow
    ├── modalManagement.js         # Modal operations (TODO)
    ├── templatePopulator.js       # SQL populator modal (TODO)
    ├── llmGeneration.js          # LLM workflows (TODO)
    └── collectionOperations.js    # CRUD operations (TODO)
```

## Modules

### 1. **utils.js** ✅ COMPLETE
**Purpose**: Pure utility functions with no side effects

**Exports**:
- `showNotification(type, message)` - Display status messages
- `populateMcpServerDropdown(selectElement)` - Populate MCP server dropdown
- `validateCollectionName(name)` - Validate collection names
- `formatDateTime(datetime)` - Format ISO datetime strings
- `sanitizeHTML(html)` - Prevent XSS attacks
- `debounce(func, wait)` - Debounce function execution
- `deepClone(obj)` - Deep clone objects

**Dependencies**: None (pure functions)

---

### 2. **templateSystem.js** ✅ COMPLETE
**Purpose**: Template card rendering, loading, and management

**Exports**:
- `initializeTemplateSystem(dropdown, callback)` - Initialize template system
- `loadTemplateCards()` - Load template cards dynamically
- `createTemplateCard(template, index)` - Create individual card element
- `getTemplateIcon(templateType)` - Get SVG icon for template type
- `reloadTemplateConfiguration(templateId)` - Reload template config from API

**Dependencies**:
- `utils.js` (showNotification)
- `window.templateManager` (global)

---

### 3. **populationWorkflow.js** ✅ COMPLETE
**Purpose**: 2-level population flow logic

**Exports**:
- `handlePopulationDecisionChange(elements)` - Level 1: None vs Template
- `handleTemplateMethodChange(elements)` - Level 2: Manual vs LLM
- `validatePopulationInputs(method, inputs)` - Validate population inputs

**Flow**:
```
Level 1: Population Decision
  ├─ None → Empty collection
  └─ Populate with Template
       ├─ Select template type
       └─ Level 2: Population Method
            ├─ Manual Entry → Fill form fields
            └─ Auto-generate → LLM generates examples
```

**Dependencies**: None

---

### 4. **modalManagement.js** 🔨 TODO
**Purpose**: Modal open/close operations with animations

**Planned Exports**:
- `openAddRagCollectionModal()`
- `closeAddRagCollectionModal()`
- `openEditCollectionModal(collectionId)`
- `closeEditCollectionModal()`
- `openSqlTemplatePopulator()`
- `closeSqlTemplateModal()`

**Dependencies**:
- `utils.js` (populateMcpServerDropdown)
- `llmGeneration.js` (checkLlmConfiguration)

---

### 5. **templatePopulator.js** 🔨 TODO
**Purpose**: SQL Template Populator modal logic

**Planned Exports**:
- `addSqlExample()`
- `removeSqlExample(exampleId)`
- `submitSqlTemplate(examples)`
- `addCollectionTemplateExample()`

**Dependencies**:
- `utils.js` (showNotification)
- API endpoints

---

### 6. **llmGeneration.js** 🔨 TODO
**Purpose**: LLM auto-generation workflows

**Planned Exports**:
- `checkLlmConfiguration()` - Check if LLM is configured
- `handleGenerateContext()` - Generate context from topic
- `handleGenerateQuestions()` - Generate question/SQL pairs
- `refreshQuestionGenerationPrompt()` - Update prompt preview

**Dependencies**:
- `utils.js` (showNotification)
- API endpoints

---

### 7. **collectionOperations.js** 🔨 TODO
**Purpose**: CRUD operations for RAG collections

**Planned Exports**:
- `createCollection(data)` - Create new collection
- `editCollection(id, data)` - Update existing collection
- `deleteCollection(id)` - Delete collection
- `toggleCollection(id)` - Toggle collection active state
- `refreshCollection(id)` - Refresh collection data
- `calculateRagImpactKPIs(collectionData)` - Calculate KPIs

**Dependencies**:
- `utils.js` (showNotification, formatDateTime)
- API endpoints

---

## Migration Strategy

### Phase 1: Foundation ✅ COMPLETE
- [x] Create module directory structure
- [x] Extract `utils.js`
- [x] Extract `templateSystem.js`
- [x] Extract `populationWorkflow.js`

### Phase 2: Gradual Adoption (Current)
- [ ] Update main file to import and use extracted modules
- [ ] Test that existing functionality works
- [ ] Add module script tags to index.html

### Phase 3: Continue Extraction
- [ ] Extract modal management
- [ ] Extract template populator
- [ ] Extract LLM generation
- [ ] Extract collection operations

### Phase 4: Cleanup
- [ ] Remove duplicated code from main file
- [ ] Update all import paths
- [ ] Add JSDoc comments
- [ ] Add unit tests

## Usage Example

### Before Refactoring:
```javascript
// Everything in ragCollectionManagement.js (3034 lines)
function showNotification(type, message) { /*...*/ }
function loadTemplateCards() { /*...*/ }
function handlePopulationDecisionChange() { /*...*/ }
// ... 3000 more lines
```

### After Refactoring:
```javascript
// ragCollectionManagement.js (coordinator)
import { showNotification } from './rag/utils.js';
import { initializeTemplateSystem, loadTemplateCards } from './rag/templateSystem.js';
import { handlePopulationDecisionChange } from './rag/populationWorkflow.js';

// Initialize
await initializeTemplateSystem(ragCollectionTemplateType, switchTemplateFields);

// Use
showNotification('success', 'Template loaded!');
```

## Benefits

1. **Maintainability**: Find code by feature, not line number
2. **Testability**: Each module can be unit tested in isolation
3. **Reusability**: Utils and template system can be reused elsewhere
4. **Collaboration**: Multiple developers can work on different modules
5. **Performance**: Browser can cache modules separately
6. **Code Organization**: Clear separation of concerns

## Next Steps

1. Update `index.html` to include module script tags
2. Update main `ragCollectionManagement.js` to import modules
3. Test all functionality works with new structure
4. Continue extracting remaining modules
5. Add unit tests for each module

## Notes

- All modules use ES6 export/import syntax
- Modules are side-effect free where possible
- DOM element references stay in main coordinator file
- Event listeners registered in main file, delegate to module functions
