# Admin User Management UI Update Guide

This document outlines the required frontend changes for the admin user management console to support account activation and deactivation. The backend has already been updated to support these features.

## 1. User List Filtering

The user list in the admin console should be updated to allow filtering by user status.

- **Current State:** The UI likely only shows active users.
- **Required Change:** Add a filter control (e.g., a dropdown or tabs) with the options: "All", "Active", and "Inactive".
- **API Integration:** When a filter is selected, call the `GET /api/v1/admin/users` endpoint with the corresponding `status` query parameter.
  - For "All": `GET /api/v1/admin/users?status=all`
  - For "Active": `GET /api/v1/admin/users?status=active`
  - For "Inactive": `GET /api/v1/admin/users?status=inactive`

## 2. Displaying User Status

The user list table or grid should be updated to visually indicate the status of each user.

- **Required Change:**
  - Add a "Status" column or a badge next to the user's name.
  - Display "Active" (e.g., with a green dot) for users where `is_active: true`.
  - Display "Inactive" (e.g., with a red or gray dot) for users where `is_active: false`.

## 3. Activate/Deactivate Functionality

The current "Delete" functionality should be replaced with explicit "Activate" and "Deactivate" actions.

- **Current State:** A "Delete" button exists, which performs a soft-delete (deactivation).
- **Required Change:**
  - Remove the "Delete" button.
  - For active users, show a "Deactivate" button.
  - For inactive users, show an "Activate" button.
- **API Integration:** Both actions will use the `PATCH /api/v1/admin/users/<user_id>` endpoint.
  - **To Deactivate:** Send a `PATCH` request with the following JSON body:
    ```json
    {
      "is_active": false
    }
    ```
  - **To Activate:** Send a `PATCH` request with the following JSON body:
    ```json
    {
      "is_active": true
    }
    ```
- **User Experience:**
  - After a successful action, the UI should refresh the user list to reflect the new status.
  - It is recommended to add a confirmation dialog before deactivating a user (e.g., "Are you sure you want to deactivate this user? They will not be able to log in.").
