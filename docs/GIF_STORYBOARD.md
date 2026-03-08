# Uderia Platform Demo GIF - Detailed Storyboard

**Target Duration**: 60-90 seconds
**Resolution**: 1280x720
**Frame Rate**: 15 fps
**Total File Size Target**: ~15-20MB

---

## 🎬 Scene-by-Scene Breakdown

### Scene 1: Opening - Main Interface (0:00-0:08, 8 seconds)

**Screen Content:**
- Full application interface showing:
  - Left panel: Session list with 3-4 sessions
  - Center: Chat canvas with 2-3 message exchanges visible
  - Right: Live Status window showing "Waiting for a new request..."
  - Bottom: Input box with placeholder "Ask me anything..."

**Actions:**
1. Start with cursor in center of screen (static 1 sec)
2. Slowly move cursor to session list, hover over active session (1 sec)
3. Move to input box, click to focus (1 sec)
4. Type slowly: "Show me all products with low inventory" (3 sec)
5. Hover over send button (1 sec)
6. Click send (1 sec)

**Key Elements to Highlight:**
- Clean, professional interface
- Session isolation (multiple sessions visible)
- Simple query input

**Optional Text Overlay:**
```
"From Intent to Autonomy"
Your AI organization that delivers
```

---

### Scene 2: Live Execution Trace (0:08-0:18, 10 seconds)

**Screen Content:**
- Live Status window becomes active
- Shows real-time execution phases:
  - "Strategic Planning in Progress..."
  - Phase indicators: Phase 1/2, Phase 2/2
  - Tool execution: "base_readQuery"
  - Results preview

**Actions:**
1. Watch Live Status populate (3 sec)
2. Scroll down in Live Status to show full trace (2 sec)
3. Highlight token counters updating in real-time (2 sec)
4. Show cost calculation appearing (1 sec)
5. Final result appears in chat (2 sec)

**Key Elements to Highlight:**
- Real-time transparency (not a black box)
- Strategic planning → Tactical execution flow
- Token/cost tracking
- Self-correction indicators (if error occurs, show recovery)

**Optional Text Overlay:**
```
"From Guesswork to Clarity"
Full transparency for absolute trust
```

---

### Scene 3: IFOC Profile Switching (0:18-0:28, 10 seconds)

**Screen Content:**
- Input box with @TAG syntax
- Profile indicator changing
- Different execution patterns

**Actions:**
1. Clear input box (1 sec)
2. Type: "@CHAT What is the capital of France?" (3 sec)
3. Send and show fast response (no tools, direct LLM) (2 sec)
4. Type: "@FOCUS What does our policy say about refunds?" (3 sec)
5. Show knowledge repository retrieval in Live Status (3 sec)

**Key Elements to Highlight:**
- @TAG syntax for instant mode switching
- Four profile icons/colors visible:
  - 🟢 IDEATE (green)
  - 🔵 FOCUS (blue)
  - 🟠 OPTIMIZE (orange)
  - 🟣 COORDINATE (purple)
- Profile indicator updating
- Different execution patterns per profile

**Optional Text Overlay:**
```
"From Ideation to Operationalization"
Four modes. One conversation. Zero friction.
```

---

### Scene 4: Setup - MCP Servers (0:28-0:35, 7 seconds)

**Screen Content:**
- Click "Setup" button
- MCP Servers panel opens
- Shows configured server with status indicators

**Actions:**
1. Click "Setup" in top navigation (1 sec)
2. MCP Servers tab auto-selected (1 sec)
3. Scroll to show server list with status (2 sec)
4. Hover over "Connected" status indicator (green) (1 sec)
5. Briefly show server details (host, port, tools count) (2 sec)

**Key Elements to Highlight:**
- Easy server configuration
- Real-time connection status
- Tool count (e.g., "30 tools available")
- Clean tabbed interface

---

### Scene 5: Setup - LLM Configurations (0:35-0:43, 8 seconds)

**Screen Content:**
- Switch to LLM Configurations tab
- Shows multiple providers configured
- Model selection interface

**Actions:**
1. Click "LLM Configurations" tab (1 sec)
2. Scroll to show provider list (Google, Anthropic, OpenAI, Azure, AWS, Friendli, Ollama) (2 sec)
3. Click on one provider to expand (1 sec)
4. Show model dropdown with toggle: "Recommended" vs "All Models" (2 sec)
5. Toggle between modes to show filtered list (2 sec)

**Key Elements to Highlight:**
- Multi-provider support (7 providers visible)
- Model filter toggle (Recommended/All)
- Active configuration indicator
- Cost-per-token display

**Optional Text Overlay:**
```
"Multi-Provider Intelligence"
One platform. Seven providers. Infinite possibilities.
```

---

### Scene 6: Setup - Profiles (0:43-0:52, 9 seconds)

**Screen Content:**
- Switch to Profiles tab
- Shows IFOC profile classes with visual indicators
- Profile configuration interface

**Actions:**
1. Click "Profiles" tab (1 sec)
2. Show profile list with icons and colors:
   - 🟢 "IDEATE - Brainstorming" (green)
   - 🔵 "FOCUS - Policy Check" (blue)
   - 🟠 "OPTIMIZE - SQL Expert" (orange, default star)
   - 🟣 "COORDINATE - Executive" (purple)
3. Click on OPTIMIZE profile to expand (2 sec)
4. Show configuration:
   - MCP Server: Teradata MCP
   - LLM Provider: Google Gemini
   - Profile Class: tool_enabled (Efficiency Focused)
   - Tools enabled: 30
5. Scroll to show RAG collection linked (2 sec)
6. Hover over "Set as Default" button (1 sec)

**Key Elements to Highlight:**
- Visual IFOC classification (colors + icons)
- Profile = MCP Server + LLM Provider + RAG Collections
- Default profile indicator (star)
- Tag syntax preview ("Use @OPTIMIZER to activate")

---

### Scene 7: RAG Collection Management (0:52-1:02, 10 seconds)

**Screen Content:**
- Close Setup, navigate to RAG Collections
- Shows collection creation workflow
- Question generation interface

**Actions:**
1. Click "RAG Collections" in navigation (1 sec)
2. Show existing collections list (1 sec)
3. Click "Create New Collection" button (1 sec)
4. Select template: "SQL Query Constructor" (1 sec)
5. Show input fields:
   - Database: Teradata
   - Count: 50 questions
6. Click "Generate Questions" button (1 sec)
7. Show progress indicator: "Generating batch 1/3..." (2 sec)
8. Preview generated questions (scrollable list) (2 sec)
9. Click "Create Collection" button (1 sec)

**Key Elements to Highlight:**
- Template-based collection creation
- Automatic LLM-assisted generation
- Batching for large sets
- Question preview before creation
- Deduplication messaging

**Optional Text Overlay:**
```
"From $$ to ¢¢¢"
Learn from every success. Optimize every query.
```

---

### Scene 8: Knowledge Repositories (1:02-1:10, 8 seconds)

**Screen Content:**
- Navigate to Knowledge Repositories
- Document upload interface
- Chunking configuration

**Actions:**
1. Click "Knowledge Repositories" in navigation (1 sec)
2. Show repository list (1 sec)
3. Click "Create Repository" button (1 sec)
4. Show configuration panel:
   - Name: "Company Policies"
   - Chunking strategy dropdown (fixed_size, semantic, paragraph, sentence)
   - Chunk size: 500
5. Select "semantic" chunking (1 sec)
6. Click "Upload Documents" (1 sec)
7. Show file picker with PDF/DOCX/TXT/MD support (1 sec)
8. Show upload progress: "Processing 3 documents..." (2 sec)

**Key Elements to Highlight:**
- Multi-format document support
- Configurable chunking strategies
- Semantic chunking for intelligent splitting
- Real-time processing feedback

**Optional Text Overlay:**
```
"From Guesswork to Clarity"
Zero hallucination. Every answer grounded.
```

---

### Scene 9: Marketplace (1:10-1:18, 8 seconds)

**Screen Content:**
- Navigate to Marketplace
- Browse community collections
- Install flow

**Actions:**
1. Click "Marketplace" in navigation (1 sec)
2. Show marketplace grid:
   - Featured collections with ratings (⭐ 4.8, ⭐ 4.5)
   - Collection icons/thumbnails
   - Download counts
   - Tags (SQL, Analytics, Healthcare, Legal)
3. Scroll through available items (2 sec)
4. Hover over collection card to show details:
   - Name, description
   - Author
   - Question count
   - Rating
5. Click "Install" button (1 sec)
6. Show confirmation: "Collection installed successfully" (1 sec)
7. Show "Installed" badge on collection (1 sec)

**Key Elements to Highlight:**
- Community-driven knowledge sharing
- Rating system (stars)
- Category filtering
- One-click installation
- Fork/customize options

**Optional Text Overlay:**
```
"Collaborative Intelligence"
Build once. Share everywhere.
```

---

### Scene 10: Agent Packs (1:18-1:25, 7 seconds)

**Screen Content:**
- Navigate to Agent Packs
- Shows installed packs
- Import/export interface

**Actions:**
1. Click "Agent Packs" in navigation (1 sec)
2. Show installed packs list:
   - "Sales Analytics Pack" (3 profiles + 2 collections)
   - "Healthcare Compliance Pack" (2 profiles + 4 collections)
3. Click on pack to expand details (2 sec)
4. Show pack contents:
   - Bundled profiles
   - Bundled collections
   - Dependencies
5. Hover over "Export Pack" button (1 sec)
6. Briefly show export options (JSON format) (1 sec)

**Key Elements to Highlight:**
- Package multiple resources
- Profile + Collection bundling
- Portable between installations
- Import/Export workflow
- Marketplace publishing option

---

### Scene 11: Administration - User Management (1:25-1:33, 8 seconds)

**Screen Content:**
- Navigate to Administration (admin only)
- User management interface
- Tier system

**Actions:**
1. Click "Administration" in navigation (1 sec)
2. Show user list table:
   - Username, Email, Tier, Status
   - Tiers: User, Developer, Admin
3. Scroll through users (2 sec)
4. Click "Add User" button (1 sec)
5. Show user creation form:
   - Username, Email, Password
   - Tier selection dropdown
   - Feature access preview based on tier
6. Show tier comparison tooltip (2 sec)
7. Close modal (1 sec)

**Key Elements to Highlight:**
- Multi-user support
- Tier-based access control (User, Developer, Admin)
- Feature gating by tier
- Email verification badges
- OAuth integration indicators

---

### Scene 12: Session Analytics (1:33-1:42, 9 seconds)

**Screen Content:**
- Navigate to User Profile → Analytics
- Cost tracking dashboard
- Token usage graphs

**Actions:**
1. Click user avatar → "Profile" (1 sec)
2. Click "Analytics" tab (1 sec)
3. Show dashboard:
   - Total tokens used (this month)
   - Total cost ($XX.XX)
   - Cost breakdown by provider (pie chart)
   - Token usage trend (line graph)
4. Scroll to session-level breakdown table (2 sec)
5. Show columns:
   - Session name
   - Prompt count
   - Input tokens, Output tokens
   - Cost
6. Hover over row to highlight (1 sec)
7. Show export button: "Download CSV" (1 sec)

**Key Elements to Highlight:**
- Real-time cost tracking
- Per-session attribution
- Provider cost comparison
- Token usage trends
- Exportable reports

**Optional Text Overlay:**
```
"From Hidden Costs to Total Visibility"
Track every token. Control every cost.
```

---

### Scene 13: Data Sovereignty - Champion Cases (1:42-1:50, 8 seconds)

**Screen Content:**
- Return to main interface
- Submit query showing sovereignty in action
- Live Status showing Champion Cases retrieval

**Actions:**
1. Return to main conversation view (1 sec)
2. Type query: "Analyze customer churn by segment" (2 sec)
3. Send query (1 sec)
4. Watch Live Status window show:
   - "Retrieving Champion Cases from RAG repository..."
   - "3 champion cases retrieved"
   - "Strategic Planning (with champion guidance)..."
   - "Executing on local infrastructure..."
5. Show status indicator: "🔒 Local Execution" (2 sec)
6. Results appear with sovereignty badge (1 sec)

**Key Elements to Highlight:**
- Champion Cases retrieval message
- Decoupled planning (cloud) vs execution (local) indicators
- Security/privacy badges
- No data exposure to cloud during execution

**Optional Text Overlay:**
```
"From Data Exposure to Data Sovereignty"
Cloud-level reasoning. Zero-trust privacy.
```

---

### Scene 14: Cost Efficiency - Fusion Optimizer (1:50-1:58, 8 seconds)

**Screen Content:**
- Live Status showing optimization in action
- Token savings indicator
- Plan hydration message

**Actions:**
1. Submit similar query to previous one (1 sec)
2. Watch Live Status show:
   - "Plan Hydration: Reusing previous database schema"
   - "Tactical Fast-Path: Skipping LLM call"
   - "Phase 1 completed in 0.2s (vs 2.1s average)"
3. Show token comparison banner:
   - "Previous query: 15,000 tokens"
   - "This query: 6,000 tokens (60% savings)"
4. Show cost comparison:
   - "Previous: $0.45"
   - "This: $0.18"
5. Highlight cumulative savings counter (2 sec)

**Key Elements to Highlight:**
- Plan hydration mechanism
- Tactical fast-path optimization
- Token usage comparison (before/after)
- Cost savings percentage
- Cumulative savings tracking

**Optional Text Overlay:**
```
"60% Cost Reduction"
$6,750/month → $2,700/month
```

---

### Scene 15: Closing - Platform Overview (1:58-2:05, 7 seconds)

**Screen Content:**
- Return to main interface
- Show all panels visible simultaneously
- Final branding

**Actions:**
1. Zoom out slightly to show full interface (1 sec)
2. Cursor moves across key areas:
   - Sessions (left)
   - Conversation (center)
   - Live Status (right)
   - Setup button (top)
   - Input box (bottom)
3. All panels briefly highlighted in sequence (3 sec)
4. Cursor returns to center (1 sec)
5. Fade to Uderia logo or tagline (2 sec)

**Final Text Overlay:**
```
Uderia Platform
Cloud-Level Reasoning. Zero-Trust Privacy.

🌐 uderia.com
```

---

## 📊 Summary Statistics

| Metric | Value |
|--------|-------|
| **Total Duration** | 2:05 (125 seconds) |
| **Number of Scenes** | 15 |
| **Panels Covered** | 12+ |
| **Transformation Statements Featured** | 6/8 |
| **Estimated File Size** | ~18-22MB @ 1280x720, 15fps |

---

## 🎨 Optional Enhancements

### Text Overlays
Add transformation statement overlays at key moments:
- Scene 1: "From Intent to Autonomy"
- Scene 2: "From Guesswork to Clarity"
- Scene 3: "From Ideation to Operationalization"
- Scene 7: "From $$ to ¢¢¢"
- Scene 12: "From Hidden Costs to Total Visibility"
- Scene 13: "From Data Exposure to Data Sovereignty"

### Visual Highlights
- Cursor spotlight effect (circular highlight around cursor)
- Brief zoom-in on key UI elements (buttons, indicators)
- Transition effects between scenes (subtle fade)

### Audio (Optional)
If creating a video version with audio:
- Background music (corporate, upbeat, 120-130 BPM)
- Sound effects for key actions (clicks, success confirmations)
- Voiceover explaining each feature

---

## 🎬 Recording Tips

### Pre-Recording Checklist
- [ ] Clean database with demo data
- [ ] 3-4 sessions created with descriptive names
- [ ] All providers configured with test API keys
- [ ] Sample RAG collections installed
- [ ] Sample knowledge repositories with 5-10 documents
- [ ] Marketplace populated (if self-hosted, seed with examples)
- [ ] User tiers set up (show different access levels)
- [ ] Browser zoom at 100% (not 90% or 110%)
- [ ] Close browser tabs/bookmarks for clean UI
- [ ] Disable browser extensions that add UI elements

### Test Queries to Prepare
1. "Show me all products with low inventory" (SQL query)
2. "What is the capital of France?" (simple chat)
3. "What does our policy say about refunds?" (knowledge retrieval)
4. "Analyze customer churn by segment" (complex analysis)

### Timing Tips
- **Slow, deliberate movements** - Cursor should move at 50% normal speed
- **Pause on key elements** - 1-2 seconds per important UI component
- **Read aloud while recording** - Helps maintain consistent pacing
- **Use a metronome** - Set to 60 BPM, do one action per beat

---

## 🔧 Post-Production Workflow

### 1. Trim Recording
```bash
# Remove dead space at beginning/end
ffmpeg -i raw_recording.mov -ss 00:00:02 -to 00:02:05 trimmed.mov
```

### 2. Add Text Overlays (Optional)
Use video editor like iMovie, DaVinci Resolve, or Kdenlive:
- Lower third text for transformation statements
- Timestamp markers for scene transitions
- Feature callout labels

### 3. Convert to GIF
```bash
# High quality conversion
ffmpeg -i trimmed.mov \
  -vf "fps=15,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=256:stats_mode=single[p];[s1][p]paletteuse=dither=bayer:bayer_scale=5" \
  -loop 0 \
  AppOverview_raw.gif
```

### 4. Optimize
```bash
# Reduce file size while maintaining quality
gifsicle -O3 --lossy=80 --colors 256 \
  AppOverview_raw.gif -o AppOverview.gif

# Check final size
du -h AppOverview.gif
```

### 5. Create Variants
```bash
# Create smaller "quick demo" version (first 30 seconds)
ffmpeg -i trimmed.mov -t 30 \
  -vf "fps=10,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  -loop 0 \
  AppOverview_Quick.gif

# Create individual scene GIFs for documentation
ffmpeg -i trimmed.mov -ss 00:00:28 -t 7 \
  -vf "fps=15,scale=1280:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  Scene04_MCP_Servers.gif
```

---

## 📁 Final Deliverables

```
images/
├── AppOverview.gif              # Full comprehensive tour (2 min)
├── AppOverview_Quick.gif        # Quick demo (30 sec)
├── scenes/
│   ├── Scene01_Interface.gif    # Individual scene clips
│   ├── Scene02_Execution.gif
│   ├── Scene03_IFOC.gif
│   ├── Scene04_MCP.gif
│   ├── Scene05_LLM.gif
│   ├── Scene06_Profiles.gif
│   ├── Scene07_RAG.gif
│   ├── Scene08_Knowledge.gif
│   ├── Scene09_Marketplace.gif
│   ├── Scene10_AgentPacks.gif
│   ├── Scene11_Admin.gif
│   ├── Scene12_Analytics.gif
│   ├── Scene13_Sovereignty.gif
│   ├── Scene14_Efficiency.gif
│   └── Scene15_Overview.gif
└── stills/
    ├── conversation.png         # High-res screenshots
    ├── live_status.png
    ├── setup_profiles.png
    └── ...
```

---

## 🎯 Quality Checklist

Before finalizing, verify:
- [ ] All 12+ panels are shown
- [ ] At least 6/8 transformation statements featured
- [ ] File size < 25MB (for GitHub rendering)
- [ ] GIF loops smoothly (no jarring transition)
- [ ] Text is readable at 720p resolution
- [ ] Color contrast sufficient on both light/dark backgrounds
- [ ] Cursor movements are smooth and deliberate
- [ ] No visible errors or broken UI elements
- [ ] All demo queries execute successfully
- [ ] Token/cost tracking displays correctly

---

## 🚀 Ready to Record!

**Quick Start Command:**
```bash
# 1. Start application
python -m trusted_data_agent.main

# 2. Open in browser
open http://localhost:5050

# 3. Login as admin
# Username: admin
# Password: admin

# 4. Start screen recording
# QuickTime → File → New Screen Recording
# Select browser window
# Follow storyboard scenes 1-15

# 5. Save and convert
# File → Save (as recording.mov)
# Run: bash create_demo_gif.sh
```

---

**Next Steps:**
1. Review this storyboard
2. Practice the recording flow 1-2 times (don't record yet)
3. Prepare test data and queries
4. Record in one take (or splice scenes together)
5. Convert and optimize
6. Update README.md with new GIF

**Estimated Time:**
- Preparation: 30 minutes
- Recording practice: 15 minutes
- Final recording: 5-10 minutes (may need 2-3 takes)
- Conversion/optimization: 10 minutes
- **Total: ~1-1.5 hours**

Good luck! 🎬
