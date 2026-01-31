/**
 * chatDocumentUpload.js
 *
 * Manages the document upload lifecycle for chat conversations.
 * Handles file selection, upload, preview, and cleanup.
 */

import * as DOM from '../domElements.js';
import { state } from '../state.js';

// --- State ---
let pendingAttachments = []; // [{file_id, filename, file_size, content_type, is_image}]
let uploadCapabilities = null;
let isUploading = false;
let dragCounter = 0; // Prevents flicker on child element drag transitions
let errorToastTimer = null;

// --- Initialization ---

/**
 * Initialize the upload UI and event listeners.
 * Called once at app startup.
 */
export function initializeUploadUI() {
    if (!DOM.fileAttachButton || !DOM.fileAttachInput) return;

    // Click handler for paperclip button
    DOM.fileAttachButton.addEventListener('click', () => {
        DOM.fileAttachInput.click();
    });

    // File selection handler
    DOM.fileAttachInput.addEventListener('change', (e) => {
        if (e.target.files && e.target.files.length > 0) {
            handleFileSelection(e.target.files);
        }
        // Reset input so same file can be selected again
        e.target.value = '';
    });

    // Drag and drop on chat form
    if (DOM.chatForm) {
        DOM.chatForm.addEventListener('dragenter', handleDragEnter);
        DOM.chatForm.addEventListener('dragover', handleDragOver);
        DOM.chatForm.addEventListener('dragleave', handleDragLeave);
        DOM.chatForm.addEventListener('drop', handleDrop);
    }
}

/**
 * Load upload capabilities for the current session's provider.
 * Shows/hides the paperclip button based on capabilities.
 */
export async function initializeUploadCapabilities(sessionId) {
    try {
        const token = localStorage.getItem('tda_auth_token');
        if (!token) return; // Not logged in yet
        const url = sessionId
            ? `/api/v1/chat/upload-capabilities?session_id=${sessionId}`
            : '/api/v1/chat/upload-capabilities';

        const response = await fetch(url, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            const data = await response.json();
            uploadCapabilities = data.capabilities;
            setUploadButtonVisibility(uploadCapabilities.enabled);
        } else {
            setUploadButtonVisibility(false);
        }
    } catch (error) {
        console.error('Failed to load upload capabilities:', error);
        setUploadButtonVisibility(false);
    }
}

// --- File Handling ---

/**
 * Validate and upload selected files.
 */
async function handleFileSelection(fileList) {
    if (!uploadCapabilities || !state.currentSessionId) return;

    const files = Array.from(fileList);
    const maxFiles = uploadCapabilities.max_files_per_message || 5;

    if (pendingAttachments.length + files.length > maxFiles) {
        showUploadError(`Maximum ${maxFiles} files per message. You have ${pendingAttachments.length} already attached.`);
        return;
    }

    // Client-side validation
    const maxSizeBytes = (uploadCapabilities.max_file_size_mb || 50) * 1024 * 1024;
    const allowedFormats = new Set(uploadCapabilities.supported_formats || []);

    for (const file of files) {
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!allowedFormats.has(ext)) {
            showUploadError(`Unsupported format: ${ext}. Allowed: ${Array.from(allowedFormats).join(', ')}`);
            return;
        }
        if (file.size > maxSizeBytes) {
            showUploadError(`File "${file.name}" exceeds ${uploadCapabilities.max_file_size_mb}MB limit.`);
            return;
        }
        if (file.size === 0) {
            showUploadError(`File "${file.name}" is empty.`);
            return;
        }
    }

    // Upload files
    isUploading = true;
    updateUploadButtonState();

    try {
        const token = localStorage.getItem('tda_auth_token');
        const formData = new FormData();
        formData.append('session_id', state.currentSessionId);
        for (const file of files) {
            formData.append('files', file);
        }

        const response = await fetch('/api/v1/chat/upload', {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` },
            body: formData
        });

        const data = await response.json();

        if (response.ok && data.status === 'success') {
            for (const fileInfo of data.files) {
                pendingAttachments.push({
                    file_id: fileInfo.file_id,
                    filename: fileInfo.original_filename,
                    file_size: fileInfo.file_size,
                    content_type: fileInfo.content_type,
                    is_image: fileInfo.is_image
                });
            }
            renderAttachmentPreview();
        } else {
            showUploadError(data.message || 'Upload failed');
        }
    } catch (error) {
        console.error('File upload error:', error);
        showUploadError('Upload failed. Please try again.');
    } finally {
        isUploading = false;
        updateUploadButtonState();
    }
}

/**
 * Remove a pending attachment by file_id with exit animation.
 */
export async function removePendingAttachment(fileId) {
    // Animate out the chip before removing
    const listContainer = document.getElementById('file-attachments-list');
    if (listContainer) {
        const chip = listContainer.querySelector(`[data-file-id="${fileId}"]`);
        if (chip) {
            chip.classList.add('attachment-chip-exit');
            await new Promise(resolve => setTimeout(resolve, 200));
        }
    }

    try {
        const token = localStorage.getItem('tda_auth_token');
        await fetch(`/api/v1/chat/upload/${fileId}?session_id=${state.currentSessionId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${token}` }
        });
    } catch (error) {
        console.error('Failed to delete upload:', error);
    }

    pendingAttachments = pendingAttachments.filter(a => a.file_id !== fileId);
    renderAttachmentPreview();
}

/**
 * Get the current pending attachments for including in chat submit.
 */
export function getPendingAttachments() {
    return [...pendingAttachments];
}

/**
 * Check if an upload is currently in progress.
 */
export function isUploadInProgress() {
    return isUploading;
}

/**
 * Clear all pending attachments after message is sent.
 */
export function clearPendingAttachments() {
    pendingAttachments = [];
    renderAttachmentPreview();
}

// --- Drag and Drop ---

function handleDragEnter(e) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter++;
    const overlay = document.getElementById('drop-zone-overlay');
    if (overlay) {
        overlay.classList.add('visible');
    }
}

function handleDragOver(e) {
    e.preventDefault();
    e.stopPropagation();
}

function handleDragLeave(e) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter--;
    if (dragCounter === 0) {
        const overlay = document.getElementById('drop-zone-overlay');
        if (overlay) {
            overlay.classList.remove('visible');
        }
    }
}

function handleDrop(e) {
    e.preventDefault();
    e.stopPropagation();
    dragCounter = 0;
    const overlay = document.getElementById('drop-zone-overlay');
    if (overlay) {
        overlay.classList.remove('visible');
    }
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
        handleFileSelection(e.dataTransfer.files);
    }
}

// --- UI Rendering ---

/**
 * Render the attachment preview area above the chat form.
 * Uses individual DOM elements instead of innerHTML for smooth animations.
 */
function renderAttachmentPreview() {
    const previewContainer = DOM.fileAttachmentsPreview;
    const listContainer = document.getElementById('file-attachments-list');
    if (!previewContainer || !listContainer) return;

    if (pendingAttachments.length === 0) {
        previewContainer.classList.remove('visible');
        // Clear after transition completes
        setTimeout(() => {
            if (pendingAttachments.length === 0) {
                listContainer.innerHTML = '';
            }
        }, 300);
        return;
    }

    previewContainer.classList.add('visible');

    // Build current file IDs
    const currentIds = new Set(pendingAttachments.map(a => a.file_id));

    // Remove chips that are no longer in pendingAttachments
    const existingChips = listContainer.querySelectorAll('[data-file-id]');
    existingChips.forEach(chip => {
        if (!currentIds.has(chip.dataset.fileId)) {
            chip.remove();
        }
    });

    // Add new chips that don't exist yet
    const existingIds = new Set(
        Array.from(listContainer.querySelectorAll('[data-file-id]'))
            .map(el => el.dataset.fileId)
    );

    for (const att of pendingAttachments) {
        if (existingIds.has(att.file_id)) continue;

        const chip = document.createElement('div');
        chip.className = 'attachment-chip inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-xs border';
        chip.dataset.fileId = att.file_id;

        // Icon (industrial single-color style for all file types)
        chip.insertAdjacentHTML('beforeend', att.is_image ? getImageIcon() : getDocumentIcon());

        // Filename
        const nameSpan = document.createElement('span');
        nameSpan.className = 'max-w-[120px] truncate';
        nameSpan.title = att.filename;
        nameSpan.textContent = att.filename;
        chip.appendChild(nameSpan);

        // File size
        const sizeSpan = document.createElement('span');
        sizeSpan.className = 'chip-filesize text-xs';
        sizeSpan.textContent = formatFileSize(att.file_size);
        chip.appendChild(sizeSpan);

        // Visual/Text badge
        const badge = document.createElement('span');
        if (att.is_image) {
            badge.className = 'text-[10px] font-semibold px-1.5 py-0.5 rounded bg-green-400/10 text-green-400';
            badge.textContent = 'Visual';
        } else {
            badge.className = 'text-[10px] font-semibold px-1.5 py-0.5 rounded bg-blue-400/10 text-blue-400';
            badge.textContent = 'Text';
        }
        chip.appendChild(badge);

        // Remove button with larger touch target
        const removeBtn = document.createElement('button');
        removeBtn.type = 'button';
        removeBtn.className = 'chip-remove-btn ml-1 p-1.5 -m-1 rounded-md transition-colors';
        removeBtn.title = 'Remove';
        removeBtn.innerHTML = '<svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';
        removeBtn.addEventListener('click', () => {
            window._removeChatAttachment(att.file_id);
        });
        chip.appendChild(removeBtn);

        listContainer.appendChild(chip);
    }
}

/**
 * Show/hide the paperclip button.
 */
function setUploadButtonVisibility(enabled) {
    if (DOM.fileAttachButton) {
        if (enabled) {
            DOM.fileAttachButton.classList.remove('hidden');
        } else {
            DOM.fileAttachButton.classList.add('hidden');
        }
    }
}

/**
 * Toggle between paperclip icon and spinner during upload.
 */
function updateUploadButtonState() {
    if (!DOM.fileAttachButton) return;

    const attachIcon = document.getElementById('attach-icon');
    const attachSpinner = document.getElementById('attach-spinner');

    DOM.fileAttachButton.disabled = isUploading;

    if (isUploading) {
        DOM.fileAttachButton.classList.add('opacity-50');
        if (attachIcon) attachIcon.classList.add('hidden');
        if (attachSpinner) attachSpinner.classList.remove('hidden');
    } else {
        DOM.fileAttachButton.classList.remove('opacity-50');
        if (attachIcon) attachIcon.classList.remove('hidden');
        if (attachSpinner) attachSpinner.classList.add('hidden');
    }
}

/**
 * Show an inline error toast above the chat form.
 * Glass-morphism styled, auto-dismisses after 4 seconds.
 */
function showUploadError(message) {
    // Clear any existing toast
    if (errorToastTimer) {
        clearTimeout(errorToastTimer);
        errorToastTimer = null;
    }

    // Find or create toast element
    let toast = document.getElementById('upload-error-toast');
    if (!toast) {
        toast = document.createElement('div');
        toast.id = 'upload-error-toast';
        toast.className = 'upload-error-toast';
        // Insert inside the chat footer's relative container
        const formParent = DOM.chatForm?.parentElement;
        if (formParent) {
            formParent.appendChild(toast);
        } else {
            document.body.appendChild(toast);
        }
    }

    toast.textContent = message;

    // Trigger show animation
    requestAnimationFrame(() => {
        toast.classList.add('visible');
    });

    // Auto-dismiss after 4 seconds
    errorToastTimer = setTimeout(() => {
        toast.classList.remove('visible');
        errorToastTimer = null;
    }, 4000);
}

// --- Helpers ---

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function getDocumentIcon() {
    return `<svg class="w-3.5 h-3.5 chip-icon flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><path fill-rule="evenodd" d="M4 4a2 2 0 012-2h4.586A2 2 0 0112 2.586L15.414 6A2 2 0 0116 7.414V16a2 2 0 01-2 2H6a2 2 0 01-2-2V4zm2 6a1 1 0 011-1h6a1 1 0 110 2H7a1 1 0 01-1-1zm1 3a1 1 0 100 2h6a1 1 0 100-2H7z" clip-rule="evenodd"></path></svg>`;
}

function getImageIcon() {
    return `<svg class="w-3.5 h-3.5 chip-icon flex-shrink-0" fill="currentColor" viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg"><path fill-rule="evenodd" d="M4 3a2 2 0 00-2 2v10a2 2 0 002 2h12a2 2 0 002-2V5a2 2 0 00-2-2H4zm12 12H4l4-8 3 6 2-4 3 6z" clip-rule="evenodd"></path></svg>`;
}

/**
 * Render file attachment chips for a chat message (used when displaying history).
 * Returns HTML string for file chips.
 */
export function renderAttachmentChips(attachments) {
    if (!attachments || attachments.length === 0) return '';

    const chips = attachments.map(att => {
        const sizeStr = formatFileSize(att.file_size);
        const icon = att.is_image ? getImageIcon() : getDocumentIcon();
        const badge = att.is_image
            ? '<span class="text-[10px] font-semibold px-1 py-0.5 rounded bg-green-400/10 text-green-400">Visual</span>'
            : '<span class="text-[10px] font-semibold px-1 py-0.5 rounded bg-blue-400/10 text-blue-400">Text</span>';
        return `
            <span class="attachment-chip inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs border">
                ${icon}
                <span class="max-w-[120px] truncate">${att.filename}</span>
                <span class="chip-filesize">${sizeStr}</span>
                ${badge}
            </span>
        `;
    }).join('');

    return `<div class="flex flex-wrap gap-1.5 mt-2">${chips}</div>`;
}

// Expose remove function globally for onclick handlers
window._removeChatAttachment = function(fileId) {
    removePendingAttachment(fileId);
};
