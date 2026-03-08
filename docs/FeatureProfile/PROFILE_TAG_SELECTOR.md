# Profile Tag Selector - Implementation Summary

## Overview
Implemented an intelligent profile tag selector that appears when users type `@` in the question input box, displaying available profiles with their tags and descriptions for easy selection.

## User Experience

### Activation
- Type `@` in the question input box
- Profile selector immediately appears showing all profiles with tags

### Display Format
```
┌─────────────────────────────────────────────┐
│ @GOGET  Google AI Full Stack               │
│ Google - Full set of MCP Capabilities...   │
├─────────────────────────────────────────────┤
│ @FRGOT  Friendly AI Full Stack             │
│ Friendly - Full set of MCP Capabilities... │
├─────────────────────────────────────────────┤
│ @OPGPT  OpenAI - 4oMini                    │
│                                             │
└─────────────────────────────────────────────┘
```

### Features
1. **Instant Display**: Shows all available profiles when typing `@`
2. **Filter as You Type**: Type `@GO` to filter profiles with tags starting with "GO"
3. **Visual Hierarchy**: 
   - Profile tag badge with orange gradient styling
   - Profile name in prominent display
   - Description text in subtle gray
4. **Keyboard Navigation**:
   - **Arrow Up/Down**: Navigate through profiles
   - **Tab/Enter**: Select highlighted profile
   - **Escape**: Close selector
5. **Mouse Support**:
   - Hover to highlight
   - Click to select
6. **Seamless Transition**: After selection, input shows `@TAG ` and autocomplete becomes active

## Implementation

### 1. HTML Structure (`templates/index.html`)
```html
<div id="profile-tag-selector" class="absolute bottom-full mb-2 w-full hidden"></div>
<div id="rag-suggestions-container" class="absolute bottom-full mb-2 w-full hidden"></div>
```

Both containers positioned above the input, profile selector shown before autocomplete.

### 2. CSS Styling (`static/css/main.css`)

#### Container Styling
```css
#profile-tag-selector {
    background: linear-gradient(135deg, rgba(40, 40, 45, 0.88), rgba(30, 30, 35, 0.92));
    backdrop-filter: blur(16px) saturate(180%);
    border: 1px solid rgba(241, 95, 34, 0.15);
    border-radius: 12px;
    max-height: 280px;
    overflow-y: auto;
    z-index: 10;
}
```

#### Profile Item Structure
```css
.profile-tag-item {
    /* Base styling with hover effects */
}

.profile-tag-header {
    display: flex;
    align-items: center;
    gap: 10px;
}

.profile-tag-badge {
    /* Orange gradient badge for @TAG */
    background: linear-gradient(135deg, rgba(241, 95, 34, 0.25), rgba(241, 95, 34, 0.15));
    border: 1px solid rgba(241, 95, 34, 0.3);
    font-family: 'Space Grotesk', monospace;
    text-transform: uppercase;
}

.profile-tag-name {
    /* Profile name display */
}

.profile-tag-description {
    /* Subtle description text */
}
```

#### Visual Effects
- Animated left border on hover (orange gradient)
- Smooth color transitions
- Premium glass morphism effect
- Consistent with app's design language

### 3. JavaScript Logic (`static/js/main.js`)

#### State Management
```javascript
let currentProfiles = [];
let profileSelectedIndex = -1;
let isShowingProfileSelector = false;
```

#### Detection Logic
```javascript
userInput.addEventListener('input', () => {
    const inputValue = userInput.value;
    
    // Detect @ at start
    if (inputValue === '@' || (inputValue.startsWith('@') && !inputValue.includes(' '))) {
        const profiles = window.configState?.profiles || [];
        const profilesWithTags = profiles.filter(p => p.tag);
        
        if (inputValue === '@') {
            // Show all profiles
            showProfileSelector(profilesWithTags);
        } else {
            // Filter by partial tag match
            const partialTag = inputValue.substring(1).toUpperCase();
            const filteredProfiles = profilesWithTags.filter(p => 
                p.tag.toUpperCase().startsWith(partialTag)
            );
            showProfileSelector(filteredProfiles);
        }
        return;
    }
    
    // Continue with normal autocomplete...
});
```

#### Profile Display
```javascript
function showProfileSelector(profiles) {
    currentProfiles = profiles;
    profileSelectedIndex = profiles.length > 0 ? 0 : -1;
    isShowingProfileSelector = true;

    profileTagSelector.innerHTML = '';
    profiles.forEach((profile, index) => {
        const profileItem = document.createElement('div');
        profileItem.className = 'profile-tag-item';
        
        // Create header with badge and name
        const header = document.createElement('div');
        header.className = 'profile-tag-header';
        
        const badge = document.createElement('span');
        badge.className = 'profile-tag-badge';
        badge.textContent = `@${profile.tag}`;
        
        const name = document.createElement('span');
        name.className = 'profile-tag-name';
        name.textContent = profile.name;
        
        header.appendChild(badge);
        header.appendChild(name);
        profileItem.appendChild(header);
        
        // Add description if available
        if (profile.description) {
            const description = document.createElement('div');
            description.className = 'profile-tag-description';
            description.textContent = profile.description;
            profileItem.appendChild(description);
        }
        
        // Event handlers...
        profileTagSelector.appendChild(profileItem);
    });
    
    profileTagSelector.classList.remove('hidden');
}
```

#### Selection Logic
```javascript
function selectProfile(index) {
    if (index >= 0 && index < currentProfiles.length) {
        const profile = currentProfiles[index];
        // Replace @ with @TAG followed by space
        userInput.value = `@${profile.tag} `;
        hideProfileSelector();
        userInput.focus();
    }
}
```

#### Keyboard Navigation
```javascript
userInput.addEventListener('keydown', (e) => {
    // Handle profile selector navigation first
    if (isShowingProfileSelector && currentProfiles.length > 0) {
        if (e.key === 'ArrowDown') {
            e.preventDefault();
            profileSelectedIndex = (profileSelectedIndex + 1) % currentProfiles.length;
            highlightProfile(profileSelectedIndex);
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            profileSelectedIndex = (profileSelectedIndex - 1 + currentProfiles.length) % currentProfiles.length;
            highlightProfile(profileSelectedIndex);
        } else if ((e.key === 'Tab' || e.key === 'Enter') && profileSelectedIndex >= 0) {
            e.preventDefault();
            selectProfile(profileSelectedIndex);
        } else if (e.key === 'Escape') {
            hideProfileSelector();
        }
        return;
    }
    
    // Handle autocomplete navigation...
});
```

## Interaction Flow

### Scenario 1: Full Tag Selection
1. User types `@`
2. Profile selector shows all profiles with tags
3. User navigates with arrow keys or hovers
4. User presses Tab/Enter or clicks
5. Input becomes `@GOGET `
6. Profile selector closes
7. Autocomplete activates for typed query

### Scenario 2: Filtered Selection
1. User types `@GO`
2. Profile selector filters to profiles with tags starting with "GO"
3. User selects desired profile
4. Input becomes `@GOGET `
5. Continue with query

### Scenario 3: Escape/Cancel
1. User types `@`
2. Profile selector appears
3. User presses Escape
4. Profile selector closes
5. Input remains as typed

## Integration with Existing Features

### Autocomplete Compatibility
- Profile selector takes precedence when `@` detected
- Once profile selected (`@TAG `), autocomplete activates normally
- Autocomplete uses selected profile's collections for suggestions

### @TAG Override System
- Works seamlessly with existing @TAG parsing in `eventHandlers.js`
- Profile selector provides discoverability for tag system
- Reduces memorization burden for users

### Configuration State
- Reads from `window.configState.profiles`
- Filters profiles without tags automatically
- Syncs with profile management changes

## Design Decisions

### 1. Trigger on `@` Only
- Clean, intuitive activation
- Doesn't interfere with normal typing
- Familiar pattern from social media/chat apps

### 2. Show All Profiles Initially
- No guessing required
- Clear overview of available options
- Fast selection for power users

### 3. Filter as You Type
- Reduces list for many profiles
- Helps with partial tag memory
- Smooth progressive disclosure

### 4. Badge-Prominent Design
- Tags are the primary identifier
- Visual distinction from profile names
- Memorable orange gradient matches app theme

### 5. Description as Secondary Info
- Provides context without clutter
- Helps differentiate similar profiles
- Optional (handles empty descriptions gracefully)

## Benefits

1. **Discoverability**: Users don't need to memorize profile tags
2. **Speed**: Quick selection via keyboard or mouse
3. **Visual Feedback**: Clear highlighting and hover states
4. **Consistency**: Matches autocomplete styling and behavior
5. **Accessibility**: Supports both keyboard and mouse interaction
6. **Progressive Enhancement**: Works alongside existing features

## Testing Checklist

- [x] Type `@` shows profile selector
- [x] All profiles with tags displayed
- [x] Profile badge, name, and description render correctly
- [x] Arrow keys navigate profiles
- [x] Tab/Enter selects highlighted profile
- [x] Escape closes selector
- [x] Mouse hover highlights profiles
- [x] Mouse click selects profile
- [x] Selected profile inserts `@TAG ` into input
- [x] Profile selector closes after selection
- [x] Autocomplete activates after profile selection
- [x] Partial tag filtering (e.g., `@GO` filters profiles)
- [x] Profile selector hides when typing continues after space
- [x] Blur event closes selector
- [x] No conflicts with autocomplete
- [x] Visual styling matches app theme

## Future Enhancements

1. **Recent Profile History**: Show recently used profiles at top
2. **Fuzzy Matching**: Allow typo-tolerant tag search
3. **Profile Icons**: Visual icons for different profile types
4. **Keyboard Shortcuts**: Direct profile selection (e.g., `@1`, `@2`)
5. **Profile Preview**: Show more details on hover (LLM, MCP server)
6. **Tag Aliases**: Support multiple tags per profile
7. **Smart Suggestions**: Suggest profiles based on query context
