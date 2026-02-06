/**
 * ⚠️ DEBUG-ONLY MODULE ⚠️
 *
 * Scroll Debugging Utility for Status Window
 *
 * PURPOSE: Diagnose scroll behavior issues in the Live Status window
 *
 * WHEN TO USE:
 * - Status window content not scrolling as expected
 * - Debugging auto-scroll to bottom behavior
 * - Investigating CSS overflow issues
 * - Testing scroll restoration after session switch
 *
 * HOW TO USE:
 * 1. Open browser DevTools console
 * 2. Import debug function: import { debugStatusWindowScroll } from './scrollDebug.js'
 * 3. Run: debugStatusWindowScroll()
 * 4. Review console output for element dimensions, overflow state, CSS properties
 *
 * WARNING: This module is NOT used in production code. It is imported on-demand
 * in the browser console for debugging purposes only. Do not import in main.js
 * or other production modules.
 *
 * @module scrollDebug
 * @category Debug Utilities
 * @deprecated Consider moving to static/js/debug/ directory in future refactoring
 */

export function debugStatusWindowScroll() {
    console.clear();
    console.log('%c=== STATUS WINDOW SCROLL DIAGNOSTIC ===', 'color: #F15F22; font-size: 14px; font-weight: bold;');
    
    // Get all relevant elements
    const statusWindow = document.getElementById('status-window');
    const statusHeader = statusWindow?.querySelector('header');
    const statusContent = document.getElementById('status-window-content');
    
    console.log('\n%c1. ELEMENT EXISTENCE CHECK', 'color: #0088ff; font-weight: bold;');
    console.log('   #status-window:', !!statusWindow);
    console.log('   header:', !!statusHeader);
    console.log('   #status-window-content:', !!statusContent);
    
    if (!statusContent) {
        console.error('   ❌ CRITICAL: #status-window-content not found!');
        return;
    }
    
    // Dimensions
    console.log('\n%c2. DIMENSIONS & OVERFLOW CHECK', 'color: #0088ff; font-weight: bold;');
    console.log('   Content scrollHeight:', statusContent.scrollHeight, 'px');
    console.log('   Content clientHeight:', statusContent.clientHeight, 'px');
    console.log('   Content offsetHeight:', statusContent.offsetHeight, 'px');
    console.log('   Content innerHTML length:', statusContent.innerHTML.length, 'chars');
    console.log('   Can scroll:', statusContent.scrollHeight > statusContent.clientHeight);
    
    if (statusContent.scrollHeight <= statusContent.clientHeight) {
        console.warn('   ⚠️  WARNING: Content height <= client height. Content might not overflow.');
        console.log('   Content children count:', statusContent.children.length);
        Array.from(statusContent.children).forEach((child, i) => {
            console.log(`     Child ${i}: offsetHeight=${child.offsetHeight}px, tagName=${child.tagName}`);
        });
    }
    
    // Parent dimensions
    console.log('\n%c3. PARENT (#status-window) CHECK', 'color: #0088ff; font-weight: bold;');
    console.log('   Dimensions:', statusWindow.clientWidth, 'x', statusWindow.clientHeight);
    console.log('   ScrollHeight:', statusWindow.scrollHeight);
    console.log('   ScrollWidth:', statusWindow.scrollWidth);
    console.log('   Parent rect:', {
        top: statusWindow.getBoundingClientRect().top,
        bottom: statusWindow.getBoundingClientRect().bottom,
        height: statusWindow.getBoundingClientRect().height
    });
    
    // Computed styles
    console.log('\n%c4. COMPUTED CSS STYLES', 'color: #0088ff; font-weight: bold;');
    const contentComputed = window.getComputedStyle(statusContent);
    const windowComputed = window.getComputedStyle(statusWindow);
    const headerComputed = window.getComputedStyle(statusHeader);
    
    console.log('   Content:');
    console.log('     - display:', contentComputed.display);
    console.log('     - overflow-y:', contentComputed.overflowY);
    console.log('     - overflow-x:', contentComputed.overflowX);
    console.log('     - flex:', contentComputed.flex);
    console.log('     - height:', contentComputed.height);
    console.log('     - max-height:', contentComputed.maxHeight);
    console.log('     - min-height:', contentComputed.minHeight);
    console.log('     - position:', contentComputed.position);
    
    console.log('   Parent (#status-window):');
    console.log('     - display:', windowComputed.display);
    console.log('     - flex-direction:', windowComputed.flexDirection);
    console.log('     - overflow:', windowComputed.overflow);
    console.log('     - height:', windowComputed.height);
    
    console.log('   Header:');
    console.log('     - flex-shrink:', headerComputed.flexShrink);
    console.log('     - height:', headerComputed.height);
    
    // Check for scrollability
    console.log('\n%c5. SCROLLABILITY ANALYSIS', 'color: #0088ff; font-weight: bold;');
    const isScrollable = statusContent.scrollHeight > statusContent.clientHeight;
    console.log('   Is scrollable:', isScrollable ? '✅ YES' : '❌ NO');
    console.log('   scrollTop:', statusContent.scrollTop);
    console.log('   Can set scrollTop:', canSetScrollTop(statusContent));
    
    // Check for class issues
    console.log('\n%c6. CLASS ANALYSIS', 'color: #0088ff; font-weight: bold;');
    console.log('   Content classes:', statusContent.className);
    console.log('   Parent classes:', statusWindow.className);
    console.log('   Header classes:', statusHeader?.className);
    
    // Test actual scrolling
    console.log('\n%c7. SCROLL FUNCTIONALITY TEST', 'color: #0088ff; font-weight: bold;');
    if (isScrollable) {
        const originalScrollTop = statusContent.scrollTop;
        statusContent.scrollTop = 100;
        const scrollWorked = statusContent.scrollTop === 100;
        statusContent.scrollTop = originalScrollTop;
        console.log('   Scroll test:', scrollWorked ? '✅ WORKS' : '❌ FAILED');
    } else {
        console.log('   ⚠️  Cannot test scroll - content not overflowing');
        console.log('   Trying to force scroll with test content...');
        window.testAddScrollContent();
    }
    
    // Recommendations
    console.log('\n%c8. RECOMMENDATIONS', 'color: #F15F22; font-weight: bold;');
    if (!isScrollable) {
        console.log('   ℹ️ Content needs to be taller than container to scroll');
        console.log('   Try: window.testAddScrollContent()');
    }
    
    if (contentComputed.overflowY === 'visible') {
        console.error('   ❌ overflow-y is "visible" - CSS not applied!');
    }
    
    console.log('\n%c✅ DIAGNOSTIC COMPLETE', 'color: #00aa00; font-size: 12px;');
}

function canSetScrollTop(element) {
    try {
        const originalValue = element.scrollTop;
        element.scrollTop = originalValue + 1;
        const changed = element.scrollTop !== originalValue;
        element.scrollTop = originalValue;
        return changed;
    } catch (e) {
        return false;
    }
}

/**
 * Test function to add tall content and verify scrolling works
 */
window.testAddScrollContent = function() {
    const elem = document.getElementById('status-window-content');
    const testDiv = document.createElement('div');
    testDiv.style.height = '2000px';
    testDiv.style.background = 'linear-gradient(to bottom, rgba(241,95,34,0.3), rgba(100,200,255,0.3))';
    testDiv.innerHTML = '<h3 style="color: #F15F22; padding: 20px;">TEST SCROLL CONTENT - 2000px tall</h3>';
    elem.appendChild(testDiv);
    
    console.log('Added test content. New dimensions:');
    console.log('  scrollHeight:', elem.scrollHeight);
    console.log('  clientHeight:', elem.clientHeight);
    console.log('  Can scroll:', elem.scrollHeight > elem.clientHeight);
};

// Make globally accessible for console debugging
window.debugStatusWindowScroll = debugStatusWindowScroll;
