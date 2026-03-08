# Phase 4: Marketplace UI - Manual Testing Guide

## Overview
This document provides a comprehensive testing guide for the marketplace UI implementation in Phase 4.

## Prerequisites
- Phase 1-3 completed and tested
- Application running (http://localhost:5001)
- Test user logged in
- At least one collection published to marketplace

## Test Setup

### 1. Create Test Collections
Using Phase 3 APIs or RAG maintenance UI:
```bash
# Create and publish a test collection
curl -X POST http://localhost:5001/api/v1/rag/collections \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{
    "name": "Test SQL Patterns",
    "mcp_server_name": "teradata-mcp",
    "description": "Sample SQL query patterns for testing"
  }'

# Publish it (replace <collection_id>)
curl -X POST http://localhost:5001/api/v1/rag/collections/<collection_id>/publish \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -d '{"visibility": "public"}'
```

## Test Cases

### TC1: Navigate to Marketplace View
**Steps:**
1. Open application in browser
2. Click "Marketplace" in sidebar navigation
3. Verify marketplace view loads

**Expected Results:**
- ✅ Marketplace view becomes active
- ✅ Search bar and visibility filter visible
- ✅ Collections load (or empty state shows if no collections)
- ✅ Loading spinner appears briefly then disappears

**Status:** [ ]

---

### TC2: Browse Public Collections
**Steps:**
1. Navigate to Marketplace view
2. Ensure "Public" is selected in visibility filter
3. Click "Search" button
4. Observe collection cards

**Expected Results:**
- ✅ All public collections display as cards
- ✅ Each card shows:
  - Collection name and description
  - Owner username
  - Subscriber count
  - RAG case count
  - Star rating (or "No ratings")
- ✅ Action buttons appropriate to ownership:
  - Non-owner: Subscribe, Fork, Rate
  - Owner: Publish/Update Visibility

**Status:** [ ]

---

### TC3: Search Collections
**Steps:**
1. Navigate to Marketplace view
2. Enter search term in search box (e.g., "SQL")
3. Press Enter or click "Search"
4. Verify results match search term

**Expected Results:**
- ✅ Collections filtered by search term
- ✅ Only matching collections displayed
- ✅ Empty state shows if no matches
- ✅ Results update without full page reload

**Status:** [ ]

---

### TC4: Filter by Visibility (Unlisted)
**Steps:**
1. Navigate to Marketplace view
2. Select "Unlisted" from visibility dropdown
3. Click "Search"
4. Verify only unlisted collections show

**Expected Results:**
- ✅ Filter changes to "Unlisted"
- ✅ Only unlisted collections displayed
- ✅ "Unlisted" badge visible on collection cards
- ✅ Collections refresh properly

**Status:** [ ]

---

### TC5: Subscribe to Collection
**Prerequisites:** At least one public collection not owned by current user

**Steps:**
1. Navigate to Marketplace view
2. Find a collection you don't own
3. Click "Subscribe" button
4. Wait for notification

**Expected Results:**
- ✅ Button shows "Subscribing..." during request
- ✅ Success notification appears: "Successfully subscribed to collection"
- ✅ Button changes to "Unsubscribe"
- ✅ Subscriber count increments by 1
- ✅ Collection remains visible in marketplace

**Status:** [ ]

---

### TC6: Unsubscribe from Collection
**Prerequisites:** Currently subscribed to a collection

**Steps:**
1. Navigate to Marketplace view
2. Find a subscribed collection (shows "Unsubscribe" button)
3. Click "Unsubscribe" button
4. Wait for notification

**Expected Results:**
- ✅ Button shows "Unsubscribing..." during request
- ✅ Success notification: "Successfully unsubscribed from collection"
- ✅ Button changes back to "Subscribe"
- ✅ Subscriber count decrements by 1

**Status:** [ ]

---

### TC7: Fork Collection - Modal Open/Close
**Steps:**
1. Navigate to Marketplace view
2. Find a collection you don't own
3. Click "Fork" button
4. Observe modal

**Expected Results:**
- ✅ Fork modal opens with smooth animation
- ✅ Modal shows source collection name and description
- ✅ "New Collection Name" field pre-filled with "(Fork)" suffix
- ✅ Blue info box explains forking
- ✅ Close button (X) and Cancel button both work
- ✅ Clicking outside modal closes it

**Status:** [ ]

---

### TC8: Fork Collection - Complete Workflow
**Steps:**
1. Navigate to Marketplace view
2. Click "Fork" on a collection
3. Enter custom name: "My Forked Collection"
4. Click "Fork Collection" button
5. Wait for completion

**Expected Results:**
- ✅ Button shows "Forking..." during request
- ✅ Success notification: "Successfully forked collection: My Forked Collection"
- ✅ Modal closes automatically
- ✅ Forked collection available in RAG Maintenance view
- ✅ Original collection unchanged

**Status:** [ ]

---

### TC9: Publish Collection - Modal Open/Close
**Prerequisites:** Logged in as owner of a private collection

**Steps:**
1. Navigate to RAG Maintenance view
2. Ensure you have a private/unpublished collection
3. Navigate to Marketplace view (if it appears, it's already published)
4. From RAG Maintenance, note collection details
5. Open Publish modal (if testing publish button exists in maintenance)

**Expected Results:**
- ✅ Publish modal opens
- ✅ Shows collection name and description
- ✅ Visibility dropdown has "Public" and "Unlisted" options
- ✅ Green info box explains publishing
- ✅ Modal can be closed via X or Cancel

**Status:** [ ]

---

### TC10: Publish Collection - Complete Workflow
**Prerequisites:** Owner of a collection with at least 1 RAG case

**Steps:**
1. Create/use a private collection with cases
2. Open publish modal (via RAG Maintenance or directly via API)
3. Select "Public" visibility
4. Click "Publish Collection"
5. Wait for completion

**Expected Results:**
- ✅ Button shows "Publishing..." during request
- ✅ Success notification: "Successfully published collection to marketplace"
- ✅ Modal closes
- ✅ Collection now appears in Marketplace browse
- ✅ Shows appropriate owner-only buttons

**Status:** [ ]

---

### TC11: Rate Collection - Star Selection
**Steps:**
1. Navigate to Marketplace view
2. Find a collection you don't own
3. Click "Rate" button
4. Hover over stars
5. Click different star ratings

**Expected Results:**
- ✅ Rate modal opens
- ✅ Collection name displayed
- ✅ Stars hover effect works (gray → yellow)
- ✅ Clicking a star fills it and all previous stars
- ✅ Hidden rating input updates with selected value

**Status:** [ ]

---

### TC12: Rate Collection - Submit Rating
**Steps:**
1. Navigate to Marketplace view
2. Click "Rate" on a collection
3. Select 4 stars
4. Enter review: "Great collection, very helpful!"
5. Click "Submit Rating"
6. Wait for completion

**Expected Results:**
- ✅ Button shows "Submitting..." during request
- ✅ Success notification: "Successfully submitted rating"
- ✅ Modal closes
- ✅ Collection card updates with new rating
- ✅ Average rating recalculates correctly

**Status:** [ ]

---

### TC13: Rate Collection - Rating Only (No Review)
**Steps:**
1. Navigate to Marketplace view
2. Click "Rate" on a collection
3. Select 5 stars
4. Leave review text empty
5. Click "Submit Rating"

**Expected Results:**
- ✅ Rating submits successfully
- ✅ Review is optional (no error)
- ✅ Collection rating updates

**Status:** [ ]

---

### TC14: Pagination - Multiple Pages
**Prerequisites:** More than 10 collections published

**Steps:**
1. Navigate to Marketplace view
2. Ensure more than 10 collections exist
3. Observe pagination controls
4. Click "Next" button
5. Click "Previous" button

**Expected Results:**
- ✅ Pagination shows: "Page X of Y (Z total)"
- ✅ "Previous" disabled on page 1
- ✅ "Next" disabled on last page
- ✅ Clicking Next loads next 10 collections
- ✅ Clicking Previous returns to previous page
- ✅ Page info updates correctly

**Status:** [ ]

---

### TC15: Empty State - No Collections
**Steps:**
1. Navigate to Marketplace view
2. Enter search term that matches nothing
3. Click "Search"
4. Observe empty state

**Expected Results:**
- ✅ Box icon displays
- ✅ "No Collections Found" heading
- ✅ "Try adjusting your search or filters" message
- ✅ No collection cards visible
- ✅ Pagination hidden

**Status:** [ ]

---

### TC16: Glass Morphism Design Consistency
**Steps:**
1. Navigate to Marketplace view
2. Observe all UI elements
3. Compare with other views (RAG Maintenance, Conversation)

**Expected Results:**
- ✅ Collection cards use `.glass-panel` class
- ✅ Hover effect on cards (border highlight)
- ✅ Orange accent color (#F15F22) used consistently
- ✅ Typography matches app style
- ✅ Button styles consistent with rest of app
- ✅ Modal backdrop blur effect

**Status:** [ ]

---

### TC17: Responsive Star Rating Display
**Steps:**
1. Navigate to Marketplace view
2. Observe collections with various ratings
3. Check rating display accuracy

**Expected Results:**
- ✅ Full stars for whole numbers (e.g., 4.0 = 4 filled stars)
- ✅ Half star for 0.5 ratings (e.g., 3.5 = 3 filled + 1 half)
- ✅ Empty stars for remaining (e.g., 2.0 = 2 filled + 3 empty)
- ✅ "No ratings" text shows if rating = 0
- ✅ Rating value displays as decimal (e.g., "4.2")

**Status:** [ ]

---

### TC18: Error Handling - Network Failure
**Steps:**
1. Open browser dev tools (Network tab)
2. Navigate to Marketplace view
3. Throttle network to offline
4. Click "Search"
5. Observe error handling

**Expected Results:**
- ✅ Error notification appears
- ✅ Message: "Failed to load marketplace collections: ..."
- ✅ Loading spinner disappears
- ✅ Previous content remains visible (or empty state)
- ✅ App doesn't crash

**Status:** [ ]

---

### TC19: Error Handling - Subscribe Failure
**Steps:**
1. Navigate to Marketplace view
2. Subscribe to a collection
3. Immediately try to subscribe again (should fail - already subscribed)
4. Or simulate network error during subscribe

**Expected Results:**
- ✅ Error notification appears
- ✅ Message explains failure reason
- ✅ Button returns to original state
- ✅ Button re-enabled for retry

**Status:** [ ]

---

### TC20: Modal Escape Key Behavior
**Steps:**
1. Open Fork modal
2. Press Escape key
3. Repeat for Publish modal
4. Repeat for Rate modal

**Expected Results:**
- ✅ Escape key closes modal (if implemented)
- ✅ Or clicking outside modal closes it
- ✅ Form resets on close
- ✅ No errors in console

**Status:** [ ]

---

### TC21: View Refresh on Navigation
**Steps:**
1. Navigate to Marketplace view
2. Subscribe to a collection
3. Navigate to RAG Maintenance view
4. Navigate back to Marketplace view
5. Observe collection state

**Expected Results:**
- ✅ Marketplace refreshes on re-entry
- ✅ Subscription state persists (shows "Unsubscribe")
- ✅ Subscriber counts accurate
- ✅ No stale data displayed

**Status:** [ ]

---

### TC22: Owner vs Non-Owner Button Visibility
**Steps:**
1. Navigate to Marketplace view as owner
2. Publish a collection
3. Observe your own collection card
4. Log in as different user
5. View same collection
6. Compare button availability

**Expected Results:**
- ✅ Owner sees: "Publish/Update Visibility" button
- ✅ Owner does NOT see: Subscribe, Fork, Rate buttons
- ✅ Non-owner sees: Subscribe, Fork, Rate buttons
- ✅ Non-owner does NOT see: Publish button

**Status:** [ ]

---

### TC23: Subscribe Button State Persistence
**Steps:**
1. Subscribe to a collection
2. Refresh browser page
3. Navigate back to Marketplace view
4. Find the subscribed collection

**Expected Results:**
- ✅ Collection shows "Unsubscribe" (not "Subscribe")
- ✅ Subscription persisted in database
- ✅ State accurately reflects backend

**Status:** [ ]

---

### TC24: Collection Metadata Display
**Steps:**
1. Navigate to Marketplace view
2. Verify all metadata displays correctly on cards

**Expected Results:**
- ✅ Collection name (bold, prominent)
- ✅ Description (or "No description")
- ✅ Owner username (with user icon)
- ✅ Subscriber count (with users icon)
- ✅ RAG case count (with book icon)
- ✅ Star rating (visual stars + numeric)
- ✅ "Unlisted" badge if visibility=unlisted

**Status:** [ ]

---

### TC25: Form Validation - Fork Modal
**Steps:**
1. Open Fork modal
2. Clear the name field
3. Try to submit
4. Observe validation

**Expected Results:**
- ✅ Form validation prevents submission
- ✅ Browser shows "required" validation message
- ✅ Or custom notification: "Please provide a name for the forked collection"

**Status:** [ ]

---

### TC26: Form Validation - Publish Modal
**Steps:**
1. Open Publish modal
2. Leave visibility unselected
3. Try to submit
4. Observe validation

**Expected Results:**
- ✅ Validation prevents submission
- ✅ Notification: "Please select a visibility option"
- ✅ Or browser validation for required field

**Status:** [ ]

---

### TC27: Form Validation - Rate Modal
**Steps:**
1. Open Rate modal
2. Don't select any stars
3. Try to submit
4. Observe validation

**Expected Results:**
- ✅ Validation prevents submission
- ✅ Notification: "Please select a rating"
- ✅ Rating field marked as required

**Status:** [ ]

---

### TC28: CSS Animation - Modal Open/Close
**Steps:**
1. Open any modal (Fork, Publish, Rate)
2. Observe opening animation
3. Close modal
4. Observe closing animation

**Expected Results:**
- ✅ Modal fades in (opacity 0 → 100)
- ✅ Modal content scales up (scale-95 → scale-100)
- ✅ Animation smooth (300ms transition)
- ✅ Closing reverses animation
- ✅ No visual glitches

**Status:** [ ]

---

### TC29: Notification Feedback - All Actions
**Steps:**
1. Perform each action: Subscribe, Unsubscribe, Fork, Publish, Rate
2. Observe notification for each

**Expected Results:**
- ✅ Subscribe: "Successfully subscribed to collection"
- ✅ Unsubscribe: "Successfully unsubscribed from collection"
- ✅ Fork: "Successfully forked collection: [name]"
- ✅ Publish: "Successfully published collection to marketplace"
- ✅ Rate: "Successfully submitted rating"
- ✅ Notifications auto-dismiss after 5 seconds
- ✅ Success notifications styled appropriately (green)

**Status:** [ ]

---

### TC30: Console Error Checking
**Steps:**
1. Open browser dev console
2. Perform all marketplace actions
3. Monitor console for errors

**Expected Results:**
- ✅ No JavaScript errors during normal operation
- ✅ API calls logged correctly
- ✅ View switch events logged
- ✅ No 404s or failed resource loads

**Status:** [ ]

---

## Cross-Browser Testing

### Browsers to Test
- [ ] Chrome/Chromium (latest)
- [ ] Firefox (latest)
- [ ] Safari (macOS)
- [ ] Edge (latest)

### Browser-Specific Checks
- [ ] Modal animations work
- [ ] Fetch API calls succeed
- [ ] CSS grid/flexbox layouts correct
- [ ] Hover effects function
- [ ] Click events fire properly

---

## Performance Testing

### Load Time
- [ ] Marketplace view loads < 2 seconds
- [ ] Collection cards render smoothly
- [ ] No layout shift during load

### Responsiveness
- [ ] UI responsive to user actions (< 300ms)
- [ ] No lag when opening modals
- [ ] Search updates quickly

### Memory
- [ ] No memory leaks when switching views repeatedly
- [ ] Event listeners cleaned up properly

---

## Accessibility Testing (Bonus)

- [ ] Tab navigation works through all interactive elements
- [ ] Focus indicators visible
- [ ] Buttons have descriptive aria-labels
- [ ] Modals trap focus appropriately

---

## Test Summary

**Total Test Cases:** 30
**Passed:** ___
**Failed:** ___
**Blocked:** ___
**Not Tested:** ___

## Issues Found

| Issue # | Description | Severity | Status |
|---------|-------------|----------|--------|
| | | | |

## Sign-Off

**Tester:** _______________
**Date:** _______________
**Build/Commit:** _______________

## Notes

- Test with at least 3-5 published collections for meaningful results
- Create collections as different users to test ownership logic
- Verify database updates alongside UI changes
