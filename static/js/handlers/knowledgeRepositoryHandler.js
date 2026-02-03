/**
 * Knowledge Repository Handler
 * Manages Knowledge repository creation, document upload, and metadata management
 */

import { state } from '../state.js';
import { populateMcpServerDropdown } from './rag/utils.js';
import { openCollectionInspection, loadRagCollections } from '../ui.js';

/**
 * Initialize Knowledge repository handlers
 */
export function initializeKnowledgeRepositoryHandlers() {
    console.log('[Knowledge] Initializing Knowledge repository handlers...');
    
    // Modal open/close handlers
    // Note: add-knowledge-repo-btn removed - templates now have Edit/Deploy buttons
    const addConstructorBtn = document.getElementById('add-knowledge-constructor-btn');
    const modalOverlay = document.getElementById('add-knowledge-repository-modal-overlay');
    const modalClose = document.getElementById('add-knowledge-repository-modal-close');
    const modalCancel = document.getElementById('add-knowledge-repository-cancel');
    const modalForm = document.getElementById('add-knowledge-repository-form');
    
    if (addConstructorBtn) {
        addConstructorBtn.addEventListener('click', () => openKnowledgeRepositoryModal());
    }
    
    if (modalClose) {
        modalClose.addEventListener('click', () => closeKnowledgeRepositoryModal());
    }
    
    if (modalCancel) {
        modalCancel.addEventListener('click', () => closeKnowledgeRepositoryModal());
    }
    
    if (modalOverlay) {
        modalOverlay.addEventListener('click', (e) => {
            if (e.target === modalOverlay) {
                closeKnowledgeRepositoryModal();
            }
        });
    }
    
    // Form submission
    if (modalForm) {
        console.log('[Knowledge] Attaching submit handler to form during init');
        modalForm.addEventListener('submit', handleKnowledgeRepositorySubmit);
        modalForm._hasSubmitHandler = true;
    } else {
        console.warn('[Knowledge] Form element not found during init (will attach later): add-knowledge-repository-form');
    }
    
    // Chunking strategy change handler with auto-preview
    const chunkingSelect = document.getElementById('knowledge-repo-chunking');
    if (chunkingSelect) {
        chunkingSelect.addEventListener('change', (e) => {
            handleChunkingStrategyChange(e);
            triggerAutoPreview();
        });
    }
    
    // Chunk parameter change handlers with auto-preview
    const chunkSizeInput = document.getElementById('knowledge-repo-chunk-size');
    const chunkOverlapInput = document.getElementById('knowledge-repo-chunk-overlap');
    
    if (chunkSizeInput) {
        chunkSizeInput.addEventListener('change', triggerAutoPreview);
    }
    
    if (chunkOverlapInput) {
        chunkOverlapInput.addEventListener('change', triggerAutoPreview);
    }
    
    // Preview toggle button handler
    const previewToggleBtn = document.getElementById('knowledge-preview-toggle');
    if (previewToggleBtn) {
        previewToggleBtn.addEventListener('click', () => {
            previewEnabled = !previewEnabled;
            updatePreviewToggleButton();

            if (previewEnabled) {
                // Generate preview immediately when enabled
                handlePreviewChunking(false);
            } else {
                // Hide preview when disabled
                const previewResults = document.getElementById('knowledge-repo-preview-results');
                const previewEmpty = document.getElementById('knowledge-repo-preview-empty');
                if (previewResults) previewResults.classList.add('hidden');
                if (previewEmpty) {
                    previewEmpty.classList.remove('hidden');
                }
            }
        });
    }
    
    // File upload handlers
    initializeFileUpload();

    // Import collection button handler (Knowledge repositories)
    const importBtn = document.getElementById('import-knowledge-collection-btn');
    if (importBtn) {
        importBtn.addEventListener('click', async () => {
            try {
                await importKnowledgeRepository();
            } catch (error) {
                console.error('[Knowledge] Import cancelled or failed:', error);
            }
        });
    }

    // Import collection button handler (Planner repositories)
    const importPlannerBtn = document.getElementById('import-planner-collection-btn');
    if (importPlannerBtn) {
        importPlannerBtn.addEventListener('click', async () => {
            try {
                await importKnowledgeRepository();
            } catch (error) {
                console.error('[Planner] Import cancelled or failed:', error);
            }
        });
    }

    console.log('[Knowledge] Knowledge repository handlers initialized');
}

/**
 * Open the Knowledge repository modal
 */
function openKnowledgeRepositoryModal() {
    const modalOverlay = document.getElementById('add-knowledge-repository-modal-overlay');
    const modalContent = document.getElementById('add-knowledge-repository-modal-content');
    
    if (!modalOverlay || !modalContent) return;
    
    // Reset form
    const form = document.getElementById('add-knowledge-repository-form');
    if (form) form.reset();
    
    // Populate MCP server dropdown
    const mcpServerSelect = document.getElementById('knowledge-repo-mcp-server');
    if (mcpServerSelect) {
        populateMcpServerDropdown(mcpServerSelect);
        console.log('[Knowledge] MCP server dropdown populated');
    }
    
    // Reset file list
    const fileList = document.getElementById('knowledge-repo-file-list');
    const filesContainer = document.getElementById('knowledge-repo-files-container');
    if (fileList) fileList.classList.add('hidden');
    if (filesContainer) filesContainer.innerHTML = '';
    
    // Hide metadata section
    const metadata = document.getElementById('knowledge-repo-metadata');
    if (metadata) metadata.classList.add('hidden');
    
    // Hide progress section
    const progress = document.getElementById('knowledge-repo-progress');
    if (progress) progress.classList.add('hidden');
    
    // Hide chunk params initially
    const chunkParams = document.getElementById('knowledge-repo-chunk-params');
    if (chunkParams) chunkParams.classList.add('hidden');
    
    // Reset preview state
    previewEnabled = false;
    updatePreviewToggleButton();
    const previewEmpty = document.getElementById('knowledge-repo-preview-empty');
    const previewResults = document.getElementById('knowledge-repo-preview-results');
    const preview = document.getElementById('knowledge-repo-preview');
    if (previewEmpty) previewEmpty.classList.remove('hidden');
    if (previewResults) previewResults.classList.add('hidden');
    if (preview) preview.classList.add('hidden');
    
    // Reset modal to CREATE mode (not upload mode)
    const modalTitle = modalOverlay.querySelector('h2');
    if (modalTitle) {
        modalTitle.innerHTML = `
            <svg class="w-6 h-6 text-green-400 inline-block mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
            </svg>
            <span>Create Knowledge Repository</span>
        `;
    }
    
    // Show name/description fields
    const nameField = document.getElementById('knowledge-repo-name')?.closest('.mb-6');
    const descField = document.getElementById('knowledge-repo-description')?.closest('.mb-6');
    if (nameField) nameField.style.display = '';
    if (descField) descField.style.display = '';
    
    // Re-enable chunking/embedding fields (for CREATE mode)
    const strategySelect = document.getElementById('knowledge-repo-chunking');
    const sizeInput = document.getElementById('knowledge-repo-chunk-size');
    const overlapInput = document.getElementById('knowledge-repo-chunk-overlap');
    const embeddingSelect = document.getElementById('knowledge-repo-embedding');
    
    if (strategySelect) {
        strategySelect.disabled = false;
        strategySelect.classList.remove('opacity-50', 'cursor-not-allowed');
    }
    if (sizeInput) {
        sizeInput.disabled = false;
        sizeInput.classList.remove('opacity-50', 'cursor-not-allowed');
    }
    if (overlapInput) {
        overlapInput.disabled = false;
        overlapInput.classList.remove('opacity-50', 'cursor-not-allowed');
    }
    if (embeddingSelect) {
        embeddingSelect.disabled = false;
        embeddingSelect.classList.remove('opacity-50', 'cursor-not-allowed');
    }
    
    // Reset submit button
    const submitBtn = document.getElementById('add-knowledge-repository-submit');
    if (submitBtn) {
        submitBtn.textContent = 'Create Repository';
        submitBtn.disabled = true;  // Initially disabled until files are uploaded
        submitBtn.title = 'Upload at least one document to enable this button';
        delete submitBtn.dataset.uploadMode;
        delete submitBtn.dataset.collectionId;
        delete submitBtn.dataset.collectionName;
    }

    // Reset selected files
    selectedFiles = [];

    // Show modal with animation
    modalOverlay.classList.remove('hidden');
    requestAnimationFrame(() => {
        modalOverlay.classList.remove('opacity-0');
        modalContent.classList.remove('scale-95', 'opacity-0');
    });
}

/**
 * Open the Knowledge repository modal with template defaults pre-filled
 * @param {object} template - Template metadata
 * @param {object} defaults - Saved default parameters
 */
function openKnowledgeRepositoryModalWithTemplate(template, defaults = {}) {
    // First open the modal normally
    openKnowledgeRepositoryModal();
    
    // Ensure form submit handler is attached (in case form wasn't ready during init)
    const modalForm = document.getElementById('add-knowledge-repository-form');
    if (modalForm) {
        // Check if handler is already attached by checking _hasSubmitHandler flag
        if (!modalForm._hasSubmitHandler) {
            console.log('[Knowledge] Attaching submit handler (was missing)');
            modalForm.addEventListener('submit', handleKnowledgeRepositorySubmit);
            modalForm._hasSubmitHandler = true;
        } else {
            console.log('[Knowledge] Submit handler already attached');
        }
    } else {
        console.error('[Knowledge] Form not found in openKnowledgeRepositoryModalWithTemplate');
    }
    
    // DON'T clone the form - it removes all event listeners including file upload!
    // Just pre-fill the form fields with defaults
    setTimeout(() => {
        console.log('[Knowledge] Pre-filling form fields with template defaults');
        
        if (defaults.chunking_strategy) {
            const chunkingSelect = document.getElementById('knowledge-repo-chunking');
            if (chunkingSelect) {
                chunkingSelect.value = defaults.chunking_strategy;
                chunkingSelect.dispatchEvent(new Event('change'));
                console.log('[Knowledge] Pre-filled chunking strategy:', defaults.chunking_strategy);
            }
        }
        
        if (defaults.embedding_model) {
            const embeddingSelect = document.getElementById('knowledge-repo-embedding');
            if (embeddingSelect) {
                embeddingSelect.value = defaults.embedding_model;
                console.log('[Knowledge] Pre-filled embedding model:', defaults.embedding_model);
            }
        }
        
        if (defaults.chunk_size) {
            const chunkSizeInput = document.getElementById('knowledge-repo-chunk-size');
            if (chunkSizeInput) {
                chunkSizeInput.value = defaults.chunk_size;
                console.log('[Knowledge] Pre-filled chunk size:', defaults.chunk_size);
            }
        }
        
        if (defaults.chunk_overlap) {
            const chunkOverlapInput = document.getElementById('knowledge-repo-chunk-overlap');
            if (chunkOverlapInput) {
                chunkOverlapInput.value = defaults.chunk_overlap;
                console.log('[Knowledge] Pre-filled chunk overlap:', defaults.chunk_overlap);
            }
        }
    }, 100);
    
    // Add template indicator
    const modalTitle = document.querySelector('#add-knowledge-repository-modal-content h2');
    if (modalTitle && template) {
        modalTitle.innerHTML = `
            <div class="flex items-center gap-2">
                <i class="fas fa-file-alt"></i>
                <span>Create Knowledge Repository</span>
                <span class="text-xs px-2 py-1 bg-green-500/20 text-green-400 rounded">
                    From Template: ${template.display_name || template.template_id}
                </span>
            </div>
        `;
    }
}

// Expose globally for template system
window.openKnowledgeRepositoryModalWithTemplate = openKnowledgeRepositoryModalWithTemplate;

/**
 * Close the Knowledge repository modal
 */
function closeKnowledgeRepositoryModal() {
    const modalOverlay = document.getElementById('add-knowledge-repository-modal-overlay');
    const modalContent = document.getElementById('add-knowledge-repository-modal-content');
    
    if (!modalOverlay || !modalContent) return;
    
    // Hide with animation
    modalOverlay.classList.add('opacity-0');
    modalContent.classList.add('scale-95', 'opacity-0');
    
    setTimeout(() => {
        modalOverlay.classList.add('hidden');
    }, 300);
}

/**
 * Handle chunking strategy change
 */
function handleChunkingStrategyChange(e) {
    const strategy = e.target.value;
    const chunkParams = document.getElementById('knowledge-repo-chunk-params');
    
    // Show chunk size/overlap only for fixed_size strategy
    if (strategy === 'fixed_size') {
        chunkParams?.classList.remove('hidden');
    } else {
        chunkParams?.classList.add('hidden');
    }
}

/**
 * Initialize file upload handlers (drag & drop + click)
 */
function initializeFileUpload() {
    const dropzone = document.getElementById('knowledge-repo-dropzone');
    const fileInput = document.getElementById('knowledge-repo-file-input');
    
    if (!dropzone || !fileInput) return;
    
    // Click to browse
    dropzone.addEventListener('click', () => {
        fileInput.click();
    });
    
    // File selection
    fileInput.addEventListener('change', (e) => {
        handleFiles(e.target.files);
    });
    
    // Drag & drop
    dropzone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzone.classList.add('border-teradata-orange', 'bg-gray-700/20');
    });
    
    dropzone.addEventListener('dragleave', (e) => {
        e.preventDefault();
        dropzone.classList.remove('border-teradata-orange', 'bg-gray-700/20');
    });
    
    dropzone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzone.classList.remove('border-teradata-orange', 'bg-gray-700/20');
        handleFiles(e.dataTransfer.files);
    });
}

// Store selected files globally
let selectedFiles = [];
// Track if preview should auto-generate
let previewEnabled = false;

/**
 * Handle file selection
 */
function handleFiles(files) {
    const filesArray = Array.from(files);
    
    // Validate file types and sizes
    const validFiles = filesArray.filter(file => {
        const ext = file.name.split('.').pop().toLowerCase();
        const validExts = ['pdf', 'txt', 'docx', 'md'];
        const maxSize = 50 * 1024 * 1024; // 50MB
        
        if (!validExts.includes(ext)) {
            console.error(`[Knowledge] File ${file.name} has invalid format. Supported: PDF, TXT, DOCX, MD`);
            showAppBanner(`File ${file.name} has invalid format. Supported: PDF, TXT, DOCX, MD`, 'error');
            return false;
        }
        
        if (file.size > maxSize) {
            console.error(`[Knowledge] File ${file.name} exceeds 50MB limit`);
            showAppBanner(`File ${file.name} exceeds 50MB limit`, 'error');
            return false;
        }
        
        return true;
    });
    
    if (validFiles.length === 0) return;
    
    // Add to selected files
    selectedFiles = [...selectedFiles, ...validFiles];

    // Update UI
    displayFileList();

    // Enable Create Repository button now that files are uploaded
    const submitBtn = document.getElementById('add-knowledge-repository-submit');
    if (submitBtn && selectedFiles.length > 0) {
        submitBtn.disabled = false;
        submitBtn.title = `Create repository with ${selectedFiles.length} document${selectedFiles.length > 1 ? 's' : ''}`;
    }

    // Show metadata and preview sections
    const metadata = document.getElementById('knowledge-repo-metadata');
    const preview = document.getElementById('knowledge-repo-preview');
    if (metadata) metadata.classList.remove('hidden');
    if (preview) preview.classList.remove('hidden');

    // Auto-generate preview
    setTimeout(() => triggerAutoPreview(), 100);
}

/**
 * Display file list
 */
function displayFileList() {
    const fileList = document.getElementById('knowledge-repo-file-list');
    const filesContainer = document.getElementById('knowledge-repo-files-container');
    
    if (!fileList || !filesContainer) return;
    
    fileList.classList.remove('hidden');
    filesContainer.innerHTML = '';
    
    selectedFiles.forEach((file, index) => {
        const fileItem = document.createElement('div');
        fileItem.className = 'flex items-center justify-between p-2 bg-gray-700 rounded-md';
        fileItem.innerHTML = `
            <div class="flex items-center gap-2">
                <svg class="w-4 h-4 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                </svg>
                <span class="text-sm text-gray-300">${file.name}</span>
                <span class="text-xs text-gray-500">(${formatFileSize(file.size)})</span>
            </div>
            <button type="button" class="remove-file-btn p-1 text-red-400 hover:text-red-300 transition-colors" data-index="${index}">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
            </button>
        `;
        filesContainer.appendChild(fileItem);
    });
    
    // Add remove handlers
    filesContainer.querySelectorAll('.remove-file-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const index = parseInt(e.currentTarget.dataset.index);
            selectedFiles.splice(index, 1);
            displayFileList();

            // Reset file input so same file can be re-selected
            const fileInput = document.getElementById('knowledge-repo-file-input');
            if (fileInput) fileInput.value = '';

            if (selectedFiles.length === 0) {
                fileList.classList.add('hidden');
                const metadata = document.getElementById('knowledge-repo-metadata');
                if (metadata) metadata.classList.add('hidden');

                // Disable Create Repository button when no files
                const submitBtn = document.getElementById('add-knowledge-repository-submit');
                if (submitBtn) {
                    submitBtn.disabled = true;
                    submitBtn.title = 'Upload at least one document to enable this button';
                }
            } else {
                // Update button tooltip with new file count
                const submitBtn = document.getElementById('add-knowledge-repository-submit');
                if (submitBtn) {
                    submitBtn.title = `Create repository with ${selectedFiles.length} document${selectedFiles.length > 1 ? 's' : ''}`;
                }
            }
        });
    });
}

/**
 * Format file size for display
 */
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

/**
 * Handle form submission
 */
async function handleKnowledgeRepositorySubmit(e) {
    console.log('[Knowledge] ========== FORM SUBMIT HANDLER CALLED ==========');
    e.preventDefault();
    
    const submitBtn = document.getElementById('add-knowledge-repository-submit');
    const progressSection = document.getElementById('knowledge-repo-progress');
    const progressText = document.getElementById('knowledge-repo-progress-text');
    const progressBar = document.getElementById('knowledge-repo-progress-bar');
    
    // Check if we're in upload mode
    const uploadMode = submitBtn?.dataset.uploadMode === 'true';
    const existingCollectionId = submitBtn?.dataset.collectionId;
    const existingCollectionName = submitBtn?.dataset.collectionName;
    
    try {
        const token = localStorage.getItem('tda_auth_token');
        let collectionId;
        
        if (uploadMode && existingCollectionId) {
            // Upload mode: Use existing collection
            console.log('[Knowledge] Upload mode: Adding documents to existing collection:', existingCollectionName);
            collectionId = existingCollectionId;
            
            // Validate we have files
            if (selectedFiles.length === 0) {
                showAppBanner('Please select at least one document to upload', 'warning');
                return;
            }
            
            // Disable submit button
            submitBtn.disabled = true;
            submitBtn.textContent = 'Uploading...';
            
            // Show progress
            if (progressSection) {
                progressSection.classList.remove('hidden');
                if (progressText) progressText.textContent = 'Preparing upload...';
                if (progressBar) progressBar.style.width = '10%';
            }
        } else {
            // Create mode: Create new repository
            const nameInput = document.getElementById('knowledge-repo-name');
            const descInput = document.getElementById('knowledge-repo-description');
            const chunkingInput = document.getElementById('knowledge-repo-chunking');
            const embeddingInput = document.getElementById('knowledge-repo-embedding');
            
            if (!nameInput) {
                console.error('[Knowledge] Name input field not found');
                showAppBanner('Form error: Name field not found', 'error');
                return;
            }
            
            const name = nameInput.value.trim();
            const description = descInput?.value.trim() || '';
            // Get from form fields (pre-filled by template) or use minimal defaults
            const chunkingStrategy = chunkingInput?.value || 'semantic';  // Default from knowledge_repo_v1 template
            const embeddingModel = embeddingInput?.value || 'all-MiniLM-L6-v2';  // Default from template
            
            let chunkSize = 1000;  // Default from template
            let chunkOverlap = 200;  // Default from template
            
            if (chunkingStrategy === 'fixed_size') {
                chunkSize = parseInt(document.getElementById('knowledge-repo-chunk-size').value);
                chunkOverlap = parseInt(document.getElementById('knowledge-repo-chunk-overlap').value);
            }
            
            // Validate
            if (!name) {
                console.error('[Knowledge] Repository name is required');
                showAppBanner('Repository name is required', 'warning');
                return;
            }
            
            // Disable submit button
            submitBtn.disabled = true;
            submitBtn.textContent = 'Creating...';
            
            // Show progress
            if (progressSection) {
                progressSection.classList.remove('hidden');
                if (progressText) progressText.textContent = 'Creating repository...';
                if (progressBar) progressBar.style.width = '10%';
            }
            
            // Step 1: Create collection
            const createResponse = await fetch('/api/v1/rag/collections', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    name: name,
                    description: description || 'Knowledge repository',
                    repository_type: 'knowledge',
                    chunking_strategy: chunkingStrategy,
                    chunk_size: chunkSize,
                    chunk_overlap: chunkOverlap,
                    embedding_model: embeddingModel
                })
            });
            
            if (!createResponse.ok) {
                const error = await createResponse.json();
                throw new Error(error.message || 'Failed to create repository');
            }
            
            const createData = await createResponse.json();
            collectionId = createData.collection_id;
        }
        
        // Get metadata (for both create and upload modes)
        const category = document.getElementById('knowledge-repo-category')?.value.trim() || '';
        const author = document.getElementById('knowledge-repo-author')?.value.trim() || '';
        const tags = document.getElementById('knowledge-repo-tags')?.value.trim() || '';
        
        // Get chunking parameters
        const chunkingStrategy = document.getElementById('knowledge-chunking-strategy')?.value || 'semantic';
        const chunkSize = parseInt(document.getElementById('knowledge-chunk-size')?.value || '1000');
        const chunkOverlap = parseInt(document.getElementById('knowledge-chunk-overlap')?.value || '200');
        const embeddingModel = document.getElementById('knowledge-repo-embedding')?.value || 'all-MiniLM-L6-v2';
        
        if (progressBar) progressBar.style.width = '30%';
        
        // Step 2: Upload documents (if any)
        if (selectedFiles.length > 0) {
            if (progressText) progressText.textContent = `Uploading ${selectedFiles.length} documents...`;
            
            for (let i = 0; i < selectedFiles.length; i++) {
                const file = selectedFiles[i];
                
                if (progressText) {
                    progressText.textContent = `Processing ${file.name} (${i + 1}/${selectedFiles.length})...`;
                }
                
                const formData = new FormData();
                formData.append('file', file);
                formData.append('title', file.name);
                formData.append('author', author);
                formData.append('category', category);
                formData.append('tags', tags);
                formData.append('chunking_strategy', chunkingStrategy);
                formData.append('chunk_size', chunkSize.toString());
                formData.append('chunk_overlap', chunkOverlap.toString());
                formData.append('embedding_model', embeddingModel);
                formData.append('stream', 'true'); // Enable SSE streaming
                
                // Use EventSource-like approach for SSE progress updates
                const uploadResponse = await fetch(`/api/v1/knowledge/repositories/${collectionId}/documents`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    },
                    body: formData
                });
                
                if (!uploadResponse.ok) {
                    const error = await uploadResponse.json();
                    console.warn(`Failed to upload ${file.name}:`, error.message);
                    console.warn(`[Knowledge] Warning: Failed to upload ${file.name}`);
                } else if (uploadResponse.headers.get('content-type')?.includes('text/event-stream')) {
                    // Handle SSE streaming response
                    const reader = uploadResponse.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';
                    
                    try {
                        while (true) {
                            const { done, value } = await reader.read();
                            if (done) break;
                            
                            buffer += decoder.decode(value, { stream: true });
                            const lines = buffer.split('\n\n');
                            buffer = lines.pop(); // Keep incomplete message in buffer
                            
                            for (const line of lines) {
                                if (!line.trim()) continue;
                                
                                const eventMatch = line.match(/^event: (.+)$/m);
                                const dataMatch = line.match(/^data: (.+)$/m);
                                
                                if (dataMatch) {
                                    try {
                                        const data = JSON.parse(dataMatch[1]);
                                        
                                        // Update progress based on event type
                                        if (data.type === 'progress' && data.percentage) {
                                            const fileProgress = 30 + (i / selectedFiles.length) * 70;
                                            const overallProgress = fileProgress + (data.percentage / 100) * (70 / selectedFiles.length);
                                            if (progressBar) progressBar.style.width = `${overallProgress}%`;
                                            if (progressText && data.message) {
                                                progressText.textContent = `${file.name}: ${data.message}`;
                                            }
                                        } else if (data.type === 'complete') {
                                            console.log(`Successfully uploaded ${file.name}:`, data.chunks_stored, 'chunks');
                                        } else if (data.type === 'error') {
                                            console.warn(`Failed to upload ${file.name}:`, data.message);
                                        }
                                    } catch (e) {
                                        console.error('[Knowledge] Error parsing SSE data:', e);
                                    }
                                }
                            }
                        }
                    } catch (streamError) {
                        console.error('[Knowledge] Error reading stream:', streamError);
                    }
                } else {
                    console.log(`Successfully uploaded ${file.name}`);
                }
                
                // Update progress
                const progress = 30 + ((i + 1) / selectedFiles.length) * 70;
                if (progressBar) progressBar.style.width = `${progress}%`;
            }
        } else {
            if (progressBar) progressBar.style.width = '100%';
        }
        
        // Success
        const successMessage = uploadMode 
            ? `Documents uploaded to "${existingCollectionName}" successfully!`
            : `Knowledge repository created successfully!`;
        if (progressText) progressText.textContent = successMessage;
        console.log(`[Knowledge] ${successMessage}`);
        showAppBanner(successMessage, 'success');
        
        // Wait a moment then close modal
        setTimeout(() => {
            closeKnowledgeRepositoryModal();
            
            // Refresh Knowledge repositories list
            loadKnowledgeRepositories();
            
            // Reset form and upload mode flags
            selectedFiles = [];
            if (submitBtn) {
                delete submitBtn.dataset.uploadMode;
                delete submitBtn.dataset.collectionId;
                delete submitBtn.dataset.collectionName;
            }
        }, 1500);
        
    } catch (error) {
        console.error('[Knowledge] Error:', error);
        showAppBanner(error.message || 'Failed to process request', 'error');
        
        if (submitBtn) {
            submitBtn.disabled = false;
            submitBtn.textContent = uploadMode ? 'Upload Documents' : 'Create Repository';
        }
        
        if (progressSection) {
            progressSection.classList.add('hidden');
        }
    }
}

/**
 * Load and display Knowledge repositories
 */
export async function loadKnowledgeRepositories() {
    const container = document.getElementById('knowledge-repositories-container');
    if (!container) return;
    
    try {
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch('/api/v1/rag/collections', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        if (!response.ok) {
            throw new Error('Failed to load Knowledge repositories');
        }
        
        const data = await response.json();
        const knowledgeRepos = data.collections?.filter(c => c.repository_type === 'knowledge') || [];
        
        console.log('[Knowledge] Loaded repositories:', knowledgeRepos);
        if (knowledgeRepos.length > 0) {
            console.log('[Knowledge] First repo structure:', knowledgeRepos[0]);
        }
        
        if (knowledgeRepos.length === 0) {
            container.innerHTML = `
                <div class="col-span-full text-center py-12">
                    <svg class="w-16 h-16 mx-auto text-gray-600 mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <p class="text-gray-400 text-sm">No Knowledge repositories yet. Create one to get started!</p>
                </div>
            `;
            return;
        }
        
        container.innerHTML = knowledgeRepos.map(repo => createKnowledgeRepositoryCard(repo)).join('');
        
        // Attach event listeners to View and Delete buttons
        // Pass the full repository data so we don't need to fetch it again
        attachKnowledgeRepositoryCardHandlers(container, knowledgeRepos);
        
    } catch (error) {
        console.error('[Knowledge] Error loading repositories:', error);
        container.innerHTML = `
            <div class="col-span-full text-center text-red-400 text-sm">
                Failed to load Knowledge repositories
            </div>
        `;
    }
}

/**
 * Attach event listeners to Knowledge repository card buttons
 */
function attachKnowledgeRepositoryCardHandlers(container, repositories) {
    console.log('[Knowledge] Attaching handlers to repository cards');
    
    // Create a map for quick lookup by ID
    const repoMap = new Map();
    repositories.forEach(repo => {
        const repoId = repo.id || repo.collection_id;
        repoMap.set(String(repoId), repo);
    });
    
    // Toggle (Enable/Disable) button handlers
    const toggleButtons = container.querySelectorAll('.toggle-knowledge-btn');
    toggleButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const repoId = btn.dataset.repoId;
            const enabled = btn.dataset.enabled === 'true';
            if (window.ragCollectionManagement) {
                window.ragCollectionManagement.toggleRagCollection(parseInt(repoId), enabled);
            }
        });
    });
    
    // Refresh button handlers removed - refresh functionality is obsolete

    // Inspect button handlers
    const inspectButtons = container.querySelectorAll('.view-knowledge-repo-btn');
    console.log('[Knowledge] Found', inspectButtons.length, 'inspect buttons');
    
    inspectButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const repoId = btn.dataset.repoId;
            console.log('[Knowledge] Inspect button clicked for repo:', repoId);
            
            // Get repository data from the map (no API call needed)
            const repo = repoMap.get(repoId);
            if (!repo) {
                console.error('[Knowledge] Repository not found in map:', repoId);
                showAppBanner('Repository data not found', 'error');
                return;
            }
            
            console.log('[Knowledge] Opening inspection view for:', repo.collection_name);
            // Use the shared collection inspection view
            openCollectionInspection(repo.id || repo.collection_id, repo.collection_name, 'knowledge', repo);
        });
    });
    
    // Edit button handlers
    const editButtons = container.querySelectorAll('.edit-knowledge-btn');
    editButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const repoId = btn.dataset.repoId;
            const repo = repoMap.get(repoId);
            if (window.ragCollectionManagement && repo) {
                window.ragCollectionManagement.openEditCollectionModal(repo);
            }
        });
    });
    
    // Upload documents button handlers
    const uploadButtons = container.querySelectorAll('.upload-knowledge-docs-btn');
    console.log('[Knowledge] Found', uploadButtons.length, 'upload buttons');
    
    uploadButtons.forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const repoId = btn.dataset.repoId;
            const repoName = btn.dataset.repoName;
            const repo = repoMap.get(repoId);
            
            if (!repo) {
                console.error('[Knowledge] Repository not found:', repoId);
                return;
            }
            
            console.log('[Knowledge] Upload button clicked for:', repoName);
            openUploadDocumentsModal(parseInt(repoId), repoName, repo);
        });
    });

    // Export button handlers
    const exportButtons = container.querySelectorAll('.export-knowledge-repo-btn');
    console.log('[Knowledge] Found', exportButtons.length, 'export buttons');

    exportButtons.forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const repoId = btn.dataset.repoId;
            const repoName = btn.dataset.repoName;
            const repo = repoMap.get(repoId);

            if (!repo) {
                console.error('[Knowledge] Repository not found:', repoId);
                return;
            }

            console.log('[Knowledge] Export button clicked for:', repoName);
            await exportKnowledgeRepository(parseInt(repoId), repoName);
        });
    });

    // Delete button handlers
    const deleteButtons = container.querySelectorAll('.delete-knowledge-repo-btn');
    console.log('[Knowledge] Found', deleteButtons.length, 'delete buttons');
    
    deleteButtons.forEach(btn => {
        btn.addEventListener('click', async (e) => {
            e.preventDefault();
            e.stopPropagation();
            const repoId = btn.dataset.repoId;
            const repo = repoMap.get(repoId);
            
            if (!repo) {
                console.error('[Knowledge] Repository not found:', repoId);
                return;
            }
            
            console.log('[Knowledge] Delete button clicked for:', repo.collection_name);
            
            // Use the centralized delete function
            if (window.knowledgeRepositoryHandler && window.knowledgeRepositoryHandler.deleteKnowledgeRepository) {
                await window.knowledgeRepositoryHandler.deleteKnowledgeRepository(parseInt(repoId), repo.collection_name);
                // Reload after deletion
                await loadKnowledgeRepositories();
            } else {
                console.error('[Knowledge] Delete handler not available');
                showAppBanner('Delete function not available. Please refresh the page.', 'error');
            }
        });
    });
}

/**
 * Open Knowledge repository inspection modal
 */
function openKnowledgeInspectionModal(repo) {
    // Create or get modal
    let modal = document.getElementById('knowledge-inspection-modal');
    if (!modal) {
        modal = document.createElement('div');
        modal.id = 'knowledge-inspection-modal';
        modal.className = 'fixed inset-0 bg-black bg-opacity-70 flex items-center justify-center z-50 hidden opacity-0';
        modal.innerHTML = `
            <div class="glass-panel rounded-xl shadow-2xl w-full max-w-4xl max-h-[90vh] overflow-y-auto transform scale-95 opacity-0" id="knowledge-inspection-modal-content">
                <div class="sticky top-0 bg-gray-800 p-6 border-b border-gray-700 flex justify-between items-start z-10">
                    <div>
                        <h2 class="text-2xl font-bold text-white" id="knowledge-inspection-title"></h2>
                        <p class="text-gray-400 text-sm mt-1" id="knowledge-inspection-description"></p>
                    </div>
                    <button type="button" id="knowledge-inspection-close" class="p-2 hover:bg-gray-700 rounded-lg transition-colors">
                        <svg class="w-6 h-6 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                        </svg>
                    </button>
                </div>
                <div class="p-6" id="knowledge-inspection-body"></div>
            </div>
        `;
        document.body.appendChild(modal);
        
        // Close button handler
        document.getElementById('knowledge-inspection-close').addEventListener('click', () => {
            modal.classList.add('opacity-0');
            const content = document.getElementById('knowledge-inspection-modal-content');
            content.classList.add('scale-95', 'opacity-0');
            setTimeout(() => modal.classList.add('hidden'), 300);
        });
        
        // Click outside to close
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                document.getElementById('knowledge-inspection-close').click();
            }
        });
    }
    
    // Populate modal
    document.getElementById('knowledge-inspection-title').textContent = repo.collection_name;
    document.getElementById('knowledge-inspection-description').textContent = repo.description || 'Knowledge repository';
    
    const body = document.getElementById('knowledge-inspection-body');
    body.innerHTML = `
        <div class="space-y-6">
            <!-- Configuration Section -->
            <div>
                <h3 class="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <svg class="w-5 h-5 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
                    </svg>
                    Configuration
                </h3>
                <div class="grid grid-cols-2 gap-4">
                    <div class="bg-gray-800/50 p-4 rounded-lg">
                        <div class="text-sm text-gray-400 mb-1">Chunking Strategy</div>
                        <div class="text-white font-medium">${repo.chunking_strategy || 'semantic'}</div>
                    </div>
                    <div class="bg-gray-800/50 p-4 rounded-lg">
                        <div class="text-sm text-gray-400 mb-1">Embedding Model</div>
                        <div class="text-white font-medium">${repo.embedding_model || 'default'}</div>
                    </div>
                    <div class="bg-gray-800/50 p-4 rounded-lg">
                        <div class="text-sm text-gray-400 mb-1">Chunk Size</div>
                        <div class="text-white font-medium">${repo.chunk_size || 'N/A'}</div>
                    </div>
                    <div class="bg-gray-800/50 p-4 rounded-lg">
                        <div class="text-sm text-gray-400 mb-1">Chunk Overlap</div>
                        <div class="text-white font-medium">${repo.chunk_overlap || 'N/A'}</div>
                    </div>
                </div>
            </div>
            
            <!-- Statistics Section -->
            <div>
                <h3 class="text-lg font-semibold text-white mb-4 flex items-center gap-2">
                    <svg class="w-5 h-5 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"></path>
                    </svg>
                    Statistics
                </h3>
                <div class="grid grid-cols-3 gap-4">
                    <div class="bg-gray-800/50 p-4 rounded-lg text-center">
                        <div class="text-3xl font-bold text-green-400" id="inspect-doc-count-${repo.id || repo.collection_id}">
                            <svg class="animate-spin h-8 w-8 text-green-400 mx-auto" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                                <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                                <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                            </svg>
                        </div>
                        <div class="text-sm text-gray-400 mt-1">Documents</div>
                    </div>
                    <div class="bg-gray-800/50 p-4 rounded-lg text-center">
                        <div class="text-3xl font-bold text-blue-400">${repo.created_at ? new Date(repo.created_at).toLocaleDateString() : 'N/A'}</div>
                        <div class="text-sm text-gray-400 mt-1">Created</div>
                    </div>
                    <div class="bg-gray-800/50 p-4 rounded-lg text-center">
                        <div class="text-3xl font-bold text-blue-400">${repo.id || repo.collection_id}</div>
                        <div class="text-sm text-gray-400 mt-1">ID</div>
                    </div>
                </div>
            </div>
            
            <!-- Repository Type -->
            <div class="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
                <div class="flex items-center gap-3">
                    <svg class="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <div>
                        <div class="text-sm text-gray-400">Repository Type</div>
                        <div class="text-white font-medium">Knowledge Repository - Document Storage</div>
                    </div>
                </div>
            </div>
        </div>
    `;
    
    // Show modal
    modal.classList.remove('hidden');
    requestAnimationFrame(() => {
        modal.classList.remove('opacity-0');
        const content = document.getElementById('knowledge-inspection-modal-content');
        content.classList.remove('scale-95', 'opacity-0');
    });
    
    // Fetch actual document count from API
    const repoId = repo.id || repo.collection_id;
    fetchKnowledgeDocumentCount(repoId);
}

/**
 * Fetch actual document count from API (for inspection modal)
 */
async function fetchKnowledgeDocumentCount(collectionId) {
    try {
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/knowledge/repositories/${collectionId}/documents`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        const countEl = document.getElementById(`inspect-doc-count-${collectionId}`);
        if (!countEl) return;
        
        if (response.ok) {
            const data = await response.json();
            const count = data.documents ? data.documents.length : 0;
            countEl.textContent = count;
        } else {
            countEl.textContent = 'Error';
            countEl.classList.add('text-red-400');
        }
    } catch (error) {
        console.error('[Knowledge] Failed to fetch document count:', error);
        const countEl = document.getElementById(`inspect-doc-count-${collectionId}`);
        if (countEl) {
            countEl.textContent = 'Error';
            countEl.classList.add('text-red-400');
        }
    }
}

/**
 * Fetch actual document count from API (for collection card)
 */
async function fetchKnowledgeDocumentCountForCard(collectionId) {
    try {
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch(`/api/v1/knowledge/repositories/${collectionId}/documents`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });
        
        const countEl = document.getElementById(`knowledge-doc-count-${collectionId}`);
        if (!countEl) return;
        
        if (response.ok) {
            const data = await response.json();
            const count = data.documents ? data.documents.length : 0;
            countEl.textContent = count;
        } else {
            countEl.textContent = '?';
        }
    } catch (error) {
        console.error('[Knowledge] Failed to fetch document count for card:', error);
        const countEl = document.getElementById(`knowledge-doc-count-${collectionId}`);
        if (countEl) {
            countEl.textContent = '?';
        }
    }
}

/**
 * Create a Knowledge repository card HTML
 */
function createKnowledgeRepositoryCard(repo) {
    // Handle both 'id' and 'collection_id' field names
    const repoId = repo.id || repo.collection_id;
    const displayName = repo.name || repo.collection_name;
    console.log('[Knowledge] Creating card for repo:', displayName, 'with ID:', repoId);
    
    const statusClass = repo.enabled ? 'bg-green-500' : 'bg-gray-500';
    const chunkCount = repo.count || repo.example_count || 0;
    
    // Fetch actual document count (will be updated asynchronously)
    setTimeout(() => fetchKnowledgeDocumentCountForCard(repoId), 100);
    
    return `
        <div class="glass-panel p-4 rounded-lg hover:bg-white/5 transition-all" data-repo-id="${repoId}">
            <div class="flex items-start gap-3 mb-3">
                <div class="p-2 bg-green-500/20 rounded-lg relative">
                    <svg class="w-6 h-6 text-green-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
                    </svg>
                    <div class="${statusClass} w-2 h-2 rounded-full absolute top-1 right-1"></div>
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-2 mb-1">
                        <h3 class="text-base font-semibold text-white truncate">${displayName}</h3>
                        <span class="px-2 py-0.5 text-xs rounded-full ${repo.enabled ? 'bg-green-500/20 text-green-400' : 'bg-gray-500/20 text-gray-400'} flex-shrink-0">
                            ${repo.enabled ? 'Active' : 'Inactive'}
                        </span>
                        <span class="px-2 py-0.5 text-xs rounded-full bg-blue-500/20 text-blue-400 flex items-center gap-1 flex-shrink-0">
                            <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                            </svg>
                            Owner
                        </span>
                    </div>
                    ${(repo.agent_packs || []).length > 0 ? `<div class="flex flex-wrap gap-1 mb-1">${(repo.agent_packs || []).map(p =>
                        `<span class="agent-pack-badge"><svg class="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2"><path stroke-linecap="round" stroke-linejoin="round" d="M20 7l-8-4-8 4m16 0l-8 4m8-4v10l-8 4m0-10L4 7m8 4v10M4 7v10l8 4"/></svg>${p.name}</span>`
                    ).join('')}</div>` : ''}
                    <p class="text-xs text-gray-500">Collection ID: ${repoId}</p>
                </div>
            </div>
            
            <p class="text-xs text-gray-500 mb-2">
                <span class="text-gray-400">ChromaDB:</span> ${repo.collection_name}${repo.chunking_strategy ? ` | ${repo.chunking_strategy} chunking` : ''}
            </p>

            <p class="text-xs text-gray-400 mb-2">
                <span class="text-gray-500">Embedding Model:</span> ${repo.embedding_model || 'all-MiniLM-L6-v2'}
            </p>

            ${repo.description ? `<p class="text-xs text-gray-400 mb-3">${repo.description}</p>` : ''}

            <div class="text-xs text-gray-500 mb-3 flex items-center gap-3">
                <span><span id="knowledge-doc-count-${repoId}" class="text-white font-medium">...</span> documents</span>
                <span>•</span>
                <span><span class="text-white font-medium">${chunkCount}</span> chunks</span>
            </div>
            
            <div class="flex gap-2 flex-wrap">
                <button class="toggle-knowledge-btn px-3 py-1 rounded-md ${repo.enabled ? 'bg-yellow-600 hover:bg-yellow-500' : 'bg-green-600 hover:bg-green-500'} text-sm text-white" data-repo-id="${repoId}" data-enabled="${repo.enabled}">
                    ${repo.enabled ? 'Disable' : 'Enable'}
                </button>
                <button class="view-knowledge-repo-btn px-3 py-1 rounded-md bg-[#F15F22] hover:bg-[#D9501A] text-sm text-white" data-repo-id="${repoId}">
                    Inspect
                </button>
                <button class="edit-knowledge-btn px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-sm text-white" data-repo-id="${repoId}">
                    Edit
                </button>
                <button class="upload-knowledge-docs-btn px-3 py-1 rounded-md bg-blue-600 hover:bg-blue-500 text-sm text-white flex items-center gap-1" data-repo-id="${repoId}" data-repo-name="${displayName}">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path>
                    </svg>
                    Upload
                </button>
                <button class="export-knowledge-repo-btn px-3 py-1 rounded-md bg-cyan-600 hover:bg-cyan-500 text-sm text-white flex items-center gap-1" data-repo-id="${repoId}" data-repo-name="${displayName}">
                    <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                    </svg>
                    Export
                </button>
                ${(repo.agent_packs?.length > 0)
                    ? `<button class="px-3 py-1 rounded-md bg-white/5 text-sm text-gray-600 cursor-not-allowed" disabled
                            title="Managed by: ${(repo.agent_packs || []).map(p => p.name).join(', ')} — uninstall the pack(s) to remove">
                        Delete
                    </button>`
                    : `<button class="delete-knowledge-repo-btn px-3 py-1 rounded-md bg-red-600 hover:bg-red-500 text-sm text-white" data-repo-id="${repoId}">
                        Delete
                    </button>`
                }
            </div>
        </div>
    `;
}

/**
 * Render more chunks (for infinite scroll)
 */
function renderMoreChunks(count = 5) {
    const previewChunks = document.getElementById('knowledge-repo-preview-chunks');
    if (!previewChunks || !window.previewChunksData) return;
    
    const chunks = window.previewChunksData;
    const startIdx = window.previewChunksDisplayed || 0;
    const endIdx = Math.min(startIdx + count, chunks.length);
    
    // Remove "load more" indicator if it exists
    const loadMoreIndicator = previewChunks.querySelector('.load-more-indicator');
    if (loadMoreIndicator) loadMoreIndicator.remove();
    
    // Render chunks
    for (let idx = startIdx; idx < endIdx; idx++) {
        const chunk = chunks[idx];
        const chunkEl = document.createElement('div');
        chunkEl.className = 'bg-gray-700/50 rounded-lg p-4 border border-gray-600 hover:border-blue-500/50 transition-colors';
        
        const isTruncated = chunk.text.length > 500;
        const chunkId = `chunk-preview-${idx}`;
        
        chunkEl.innerHTML = `
            <div class="flex items-center justify-between mb-3">
                <span class="text-sm font-semibold text-blue-300">Chunk ${idx + 1}</span>
                <span class="text-xs px-2 py-1 rounded-full bg-gray-600 text-gray-300">${chunk.text.length} chars</span>
            </div>
            <div id="${chunkId}-text" class="text-sm text-gray-200 whitespace-pre-wrap leading-relaxed">
                ${isTruncated ? chunk.text.substring(0, 500) + '...' : chunk.text}
            </div>
            ${isTruncated ? `
                <button id="${chunkId}-toggle" class="mt-3 text-xs text-blue-400 hover:text-blue-300 underline transition-colors">
                    Show full chunk
                </button>
            ` : ''}
        `;
        
        // Add toggle functionality if truncated
        if (isTruncated) {
            const toggleBtn = chunkEl.querySelector(`#${chunkId}-toggle`);
            const textDiv = chunkEl.querySelector(`#${chunkId}-text`);
            let isExpanded = false;
            
            toggleBtn.addEventListener('click', () => {
                isExpanded = !isExpanded;
                textDiv.textContent = isExpanded ? chunk.text : chunk.text.substring(0, 500) + '...';
                toggleBtn.textContent = isExpanded ? 'Show less' : 'Show full chunk';
            });
        }
        
        previewChunks.appendChild(chunkEl);
    }
    
    window.previewChunksDisplayed = endIdx;
    
    // Add "scroll for more" indicator if there are more chunks
    if (endIdx < chunks.length) {
        const moreEl = document.createElement('div');
        moreEl.className = 'load-more-indicator text-center py-3 text-sm text-gray-400 flex items-center justify-center gap-2';
        moreEl.innerHTML = `
            <svg class="animate-bounce w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 14l-7 7m0 0l-7-7m7 7V3"></path>
            </svg>
            <span>Scroll down to load ${Math.min(5, chunks.length - endIdx)} more chunks (${chunks.length - endIdx} remaining)</span>
        `;
        previewChunks.appendChild(moreEl);
    }
}

/**
 * Setup infinite scroll for preview chunks
 */
function setupInfiniteScroll() {
    const previewChunks = document.getElementById('knowledge-repo-preview-chunks');
    if (!previewChunks) return;
    
    // Find the scrollable parent container (has overflow-y-auto class)
    const scrollContainer = previewChunks.parentElement;
    if (!scrollContainer) return;
    
    // Remove existing listener if any
    if (window.previewScrollListener) {
        scrollContainer.removeEventListener('scroll', window.previewScrollListener);
    }
    
    // Create scroll listener
    window.previewScrollListener = () => {
        const scrollTop = scrollContainer.scrollTop;
        const scrollHeight = scrollContainer.scrollHeight;
        const clientHeight = scrollContainer.clientHeight;
        
        // Load more when scrolled to bottom (with 100px threshold)
        if (scrollTop + clientHeight >= scrollHeight - 100) {
            if (window.previewChunksData && window.previewChunksDisplayed < window.previewChunksData.length) {
                renderMoreChunks(5);
            }
        }
    };
    
    scrollContainer.addEventListener('scroll', window.previewScrollListener);
}

/**
 * Update preview toggle button UI based on preview state
 */
function updatePreviewToggleButton() {
    const toggleBtn = document.getElementById('knowledge-preview-toggle');
    if (!toggleBtn) return;
    
    const icon = toggleBtn.querySelector('svg');
    const text = toggleBtn.querySelector('span');
    
    if (previewEnabled) {
        // Active state
        toggleBtn.classList.remove('bg-blue-500/20', 'hover:bg-blue-500/30', 'border-blue-500/40');
        toggleBtn.classList.add('bg-blue-500', 'hover:bg-blue-600', 'border-blue-500');
        if (icon) icon.classList.replace('text-blue-400', 'text-white');
        if (text) {
            text.textContent = 'Hide Preview';
            text.classList.replace('text-blue-300', 'text-white');
        }
    } else {
        // Inactive state
        toggleBtn.classList.remove('bg-blue-500', 'hover:bg-blue-600', 'border-blue-500');
        toggleBtn.classList.add('bg-blue-500/20', 'hover:bg-blue-500/30', 'border-blue-500/40');
        if (icon) icon.classList.replace('text-white', 'text-blue-400');
        if (text) {
            text.textContent = 'Show Preview';
            text.classList.replace('text-white', 'text-blue-300');
        }
    }
}

/**
 * Trigger auto-preview when files or settings change
 */
function triggerAutoPreview() {
    // Only auto-preview if preview is enabled and files are selected
    if (!previewEnabled || !selectedFiles || selectedFiles.length === 0) {
        return;
    }
    
    // Debounce to avoid rapid consecutive calls
    if (window.previewTimeout) {
        clearTimeout(window.previewTimeout);
    }
    
    window.previewTimeout = setTimeout(() => {
        handlePreviewChunking(true); // Pass true to indicate auto-preview
    }, 300);
}

/**
 * Handle chunking preview
 */
async function handlePreviewChunking(isAutoPreview = false) {
    if (selectedFiles.length === 0) {
        if (!isAutoPreview) {
            showAppBanner('Please select at least one document to preview chunking', 'warning');
        }
        return;
    }
    
    const previewResults = document.getElementById('knowledge-repo-preview-results');
    const previewStats = document.getElementById('knowledge-repo-preview-stats');
    const previewChunks = document.getElementById('knowledge-repo-preview-chunks');
    
    if (!previewResults || !previewStats || !previewChunks) return;
    
    // Get chunking configuration
    const chunkingStrategy = document.getElementById('knowledge-repo-chunking')?.value || 'semantic';
    let chunkSize = 1000;
    let chunkOverlap = 200;
    
    if (chunkingStrategy === 'fixed_size') {
        chunkSize = parseInt(document.getElementById('knowledge-repo-chunk-size')?.value || '1000');
        chunkOverlap = parseInt(document.getElementById('knowledge-repo-chunk-overlap')?.value || '200');
    }
    
    // Show loading state
    previewResults.classList.remove('hidden');
    previewChunks.innerHTML = '<p class="text-sm text-gray-400 text-center py-4">Processing...</p>';
    
    try {
        // For now, we'll use the first file for preview
        const file = selectedFiles[0];
        
        // Create FormData to send file
        const formData = new FormData();
        formData.append('file', file);
        formData.append('chunking_strategy', chunkingStrategy);
        formData.append('chunk_size', chunkSize);
        formData.append('chunk_overlap', chunkOverlap);
        
        // Call preview API endpoint (we'll need to create this)
        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch('/api/v1/knowledge/preview-chunking', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            body: formData
        });
        
        if (!response.ok) {
            throw new Error('Failed to generate preview');
        }
        
        const data = await response.json();
        const chunks = data.chunks || [];
        
        // Update stats
        const totalChars = data.total_characters || chunks.reduce((sum, chunk) => sum + chunk.text.length, 0);
        const isTruncated = data.is_preview_truncated;
        const fullDocChars = data.full_document_characters;
        const previewNote = data.preview_note;
        
        let statsText = `${chunks.length} chunks • ${totalChars.toLocaleString()} chars`;
        if (isTruncated && previewNote) {
            statsText += ` • ${previewNote}`;
        } else if (isTruncated) {
            statsText += ` • Preview (full doc: ${fullDocChars.toLocaleString()} chars)`;
        } else {
            statsText += ` • Avg ${Math.round(totalChars / chunks.length)} chars/chunk`;
        }
        previewStats.textContent = statsText;
        
        // Hide empty state, show results
        const previewEmpty = document.getElementById('knowledge-repo-preview-empty');
        if (previewEmpty) previewEmpty.classList.add('hidden');
        
        // Store chunks for infinite scroll
        window.previewChunksData = chunks;
        window.previewChunksDisplayed = 0;
        
        // Clear and setup infinite scroll
        previewChunks.innerHTML = '';
        renderMoreChunks(5); // Initial load: 5 chunks
        
        // Setup infinite scroll listener
        setupInfiniteScroll();
        
    } catch (error) {
        console.error('[Knowledge] Preview error:', error);
        previewChunks.innerHTML = `<p class="text-sm text-red-400 text-center py-4">Failed to generate preview: ${error.message}</p>`;
    }
}

/**
 * Open modal to upload additional documents to existing Knowledge Repository
 */
export function openUploadDocumentsModal(collectionId, collectionName, repoData) {
    console.log('[Knowledge] Opening upload documents modal for:', collectionName, 'ID:', collectionId);
    
    // Get chunking parameters from repo if available
    const chunkingStrategy = repoData?.chunking_strategy || 'semantic';
    const chunkSize = repoData?.chunk_size || 1000;
    const chunkOverlap = repoData?.chunk_overlap || 200;
    
    // Open the standard knowledge repository modal
    const modalOverlay = document.getElementById('add-knowledge-repository-modal-overlay');
    const modalContent = document.getElementById('add-knowledge-repository-modal-content');
    
    if (!modalOverlay || !modalContent) {
        console.error('[Knowledge] Modal elements not found');
        return;
    }
    
    // Reset the form
    const form = document.getElementById('add-knowledge-repository-form');
    if (form) form.reset();
    
    // Clear file selection
    selectedFiles = [];
    const fileList = document.getElementById('knowledge-repo-file-list');
    const filesContainer = document.getElementById('knowledge-repo-files-container');
    if (fileList) fileList.classList.add('hidden');
    if (filesContainer) filesContainer.innerHTML = '';
    
    // Set modal to "upload mode"
    const modalTitle = modalOverlay.querySelector('h2');
    if (modalTitle) {
        modalTitle.innerHTML = `
            <svg class="w-6 h-6 text-blue-400 inline-block mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"></path>
            </svg>
            <span>Upload Documents to ${collectionName}</span>
        `;
    }
    
    // Show and pre-populate name/description fields with existing values
    const nameInput = document.getElementById('knowledge-repo-name');
    const descInput = document.getElementById('knowledge-repo-description');
    const nameField = nameInput?.closest('.mb-6');
    const descField = descInput?.closest('.mb-6');
    
    if (nameField) nameField.style.display = '';
    if (descField) descField.style.display = '';
    
    if (nameInput) nameInput.value = collectionName || '';
    if (descInput) descInput.value = repoData?.description || '';
    
    // Pre-fill and DISABLE chunking/embedding parameters (immutable for existing repo)
    const strategySelect = document.getElementById('knowledge-repo-chunking');
    const sizeInput = document.getElementById('knowledge-repo-chunk-size');
    const overlapInput = document.getElementById('knowledge-repo-chunk-overlap');
    const embeddingSelect = document.getElementById('knowledge-repo-embedding');
    
    if (strategySelect) {
        strategySelect.value = chunkingStrategy;
        strategySelect.disabled = true;
        strategySelect.classList.add('opacity-50', 'cursor-not-allowed');
    }
    if (sizeInput) {
        sizeInput.value = chunkSize;
        sizeInput.disabled = true;
        sizeInput.classList.add('opacity-50', 'cursor-not-allowed');
    }
    if (overlapInput) {
        overlapInput.value = chunkOverlap;
        overlapInput.disabled = true;
        overlapInput.classList.add('opacity-50', 'cursor-not-allowed');
    }
    if (embeddingSelect) {
        // Set to current embedding model if available
        if (repoData?.embedding_model) {
            embeddingSelect.value = repoData.embedding_model;
        }
        embeddingSelect.disabled = true;
        embeddingSelect.classList.add('opacity-50', 'cursor-not-allowed');
    }
    
    // Reset preview state
    previewEnabled = false;
    updatePreviewToggleButton();
    
    // Update submit button
    const submitBtn = document.getElementById('add-knowledge-repository-submit');
    if (submitBtn) {
        submitBtn.textContent = 'Upload Documents';
        // Store collection ID in dataset for form submission
        submitBtn.dataset.uploadMode = 'true';
        submitBtn.dataset.collectionId = collectionId;
        submitBtn.dataset.collectionName = collectionName;
    }
    
    // Show modal with animation
    modalOverlay.classList.remove('hidden');
    requestAnimationFrame(() => {
        modalOverlay.classList.remove('opacity-0');
        modalContent.classList.remove('scale-95', 'opacity-0');
    });
}

// Note: openKnowledgeInspectionModal function is now deprecated in favor of openCollectionInspection from ui.js

/**
 * Export a knowledge repository as a .zip file
 */
export async function exportKnowledgeRepository(collectionId, collectionName) {
    try {
        console.log(`[Knowledge] Exporting collection ${collectionId}...`);

        // Show directory selection dialog
        const exportPath = await showExportDirectoryDialog(collectionName);
        if (exportPath === null) {
            // User explicitly cancelled (clicked Cancel button or ESC)
            console.log('[Knowledge] Export cancelled by user');
            return;
        }

        // Show progress banner
        if (window.showAppBanner) {
            window.showAppBanner(`Exporting "${collectionName}"...`, 'info');
        }

        const token = localStorage.getItem('tda_auth_token');

        // Check if user selected a folder via browser picker
        if (typeof exportPath === 'object' && exportPath.type === 'browser-folder') {
            // Download file to browser-selected folder using File System Access API
            const directoryHandle = exportPath.directoryHandle;

            try {
                // Fetch the file from server
                const response = await fetch(`/api/v1/rag/collections/${collectionId}/export`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.message || 'Export failed');
                }

                const blob = await response.blob();
                const fileName = `collection_${collectionId}_${collectionName.replace(/\s+/g, '_')}.zip`;

                // Try to create file in selected directory
                const fileHandle = await directoryHandle.getFileHandle(fileName, { create: true });
                const writable = await fileHandle.createWritable();
                await writable.write(blob);
                await writable.close();

                console.log('[Knowledge] Export saved to selected folder:', fileName);
                if (window.showAppBanner) {
                    window.showAppBanner(
                        `Collection exported to ${directoryHandle.name}/${fileName}`,
                        'success'
                    );
                }
            } catch (folderError) {
                console.error('[Knowledge] Browser folder export error:', folderError);

                // If folder access fails, fall back to regular browser download
                if (window.showAppBanner) {
                    window.showAppBanner(
                        'Cannot write to selected folder (may be a system directory). Downloading to browser default location...',
                        'warning'
                    );
                }

                // Fall back to regular download
                const response = await fetch(`/api/v1/rag/collections/${collectionId}/export`, {
                    method: 'GET',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    }
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.message || 'Export failed');
                }

                const blob = await response.blob();
                const fileName = `collection_${collectionId}_${collectionName.replace(/\s+/g, '_')}.zip`;
                const blobUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = fileName;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(blobUrl);
                document.body.removeChild(a);

                console.log('[Knowledge] Fell back to browser download');
            }
        } else {
            // Standard export: server-side save or browser download
            const url = exportPath
                ? `/api/v1/rag/collections/${collectionId}/export?export_path=${encodeURIComponent(exportPath)}`
                : `/api/v1/rag/collections/${collectionId}/export`;

            const response = await fetch(url, {
                method: 'GET',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Export failed');
            }

            // Check if response is JSON (server-side save) or blob (browser download)
            const contentType = response.headers.get('content-type');

            if (contentType && contentType.includes('application/json')) {
                // Server-side save - get success message
                const result = await response.json();
                console.log('[Knowledge] Export saved to server:', result.file_path);
                if (window.showAppBanner) {
                    window.showAppBanner(
                        `Collection exported to ${result.file_path} (${result.file_size_mb} MB)`,
                        'success'
                    );
                }
            } else {
                // Browser download - get blob and trigger download
                const blob = await response.blob();
                const blobUrl = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = blobUrl;
                a.download = `collection_${collectionId}_${collectionName.replace(/\s+/g, '_')}.zip`;
                document.body.appendChild(a);
                a.click();
                window.URL.revokeObjectURL(blobUrl);
                document.body.removeChild(a);

                console.log('[Knowledge] Export downloaded to browser');
                if (window.showAppBanner) {
                    window.showAppBanner(`Collection exported successfully!`, 'success');
                }
            }
        }

    } catch (error) {
        console.error('[Knowledge] Export error:', error);
        if (window.showAppBanner) {
            window.showAppBanner(`Export failed: ${error.message}`, 'error');
        }
    }
}

/**
 * Show dialog to let user specify export directory
 */
async function showExportDirectoryDialog(collectionName) {
    return new Promise((resolve) => {
        let selectedDirectoryHandle = null;

        // Check if File System Access API is supported
        const supportsFileSystemAccess = 'showDirectoryPicker' in window;

        // Create modal overlay
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';

        // Create modal content
        const modal = document.createElement('div');
        modal.className = 'bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4';
        modal.innerHTML = `
            <h3 class="text-xl font-semibold text-white mb-4">Export Collection</h3>
            <p class="text-gray-300 mb-4">Specify the directory where you want to export "${collectionName}":</p>

            <div class="mb-6">
                <label class="block text-sm font-medium text-gray-300 mb-2">Export Directory</label>
                <div class="flex gap-2">
                    <input
                        type="text"
                        id="export-path-input"
                        class="flex-1 px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                        placeholder="/path/to/export/directory"
                        value="${getDefaultExportPath()}"
                    />
                    ${supportsFileSystemAccess ? `
                    <button
                        id="export-browse-btn"
                        class="px-4 py-2 rounded-md bg-gray-700 hover:bg-gray-600 text-white border border-gray-600 transition-colors flex items-center gap-2 whitespace-nowrap"
                        title="Browse for folder"
                    >
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
                        </svg>
                        Browse...
                    </button>
                    ` : ''}
                </div>
                <p class="text-xs text-gray-400 mt-2">
                    ${supportsFileSystemAccess
                        ? 'Click "Browse..." to select a folder graphically, or enter a path manually'
                        : 'Enter server path, or leave empty to download to browser'
                    }
                </p>
            </div>

            <div class="flex justify-end space-x-3">
                <button
                    id="export-cancel-btn"
                    class="px-4 py-2 rounded-md bg-gray-600 hover:bg-gray-500 text-white transition-colors"
                >
                    Cancel
                </button>
                <button
                    id="export-confirm-btn"
                    class="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                >
                    Export
                </button>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Focus input
        const input = document.getElementById('export-path-input');
        setTimeout(() => input.focus(), 100);

        // Handle browse button (if supported)
        if (supportsFileSystemAccess) {
            const browseBtn = document.getElementById('export-browse-btn');
            browseBtn.onclick = async () => {
                try {
                    // Show native folder picker
                    const directoryHandle = await window.showDirectoryPicker({
                        mode: 'readwrite',
                        startIn: 'downloads'
                    });

                    selectedDirectoryHandle = directoryHandle;

                    // Show selected directory name in input
                    input.value = `[Selected: ${directoryHandle.name}]`;
                    input.dataset.browserSelected = 'true';

                    console.log('[Export] Selected directory:', directoryHandle.name);
                } catch (error) {
                    // User cancelled the picker or error occurred
                    if (error.name !== 'AbortError') {
                        console.error('[Export] Folder picker error:', error);
                        if (window.showAppBanner) {
                            window.showAppBanner('Failed to open folder picker', 'error');
                        }
                    }
                }
            };
        }

        // Handle confirm
        document.getElementById('export-confirm-btn').onclick = () => {
            const path = input.value.trim();

            // Save as default for next time (only if non-empty and not browser-selected)
            if (path && !input.dataset.browserSelected) {
                localStorage.setItem('tda_export_directory', path);
            }

            document.body.removeChild(overlay);

            // If user selected via browser picker, return special object
            if (selectedDirectoryHandle) {
                resolve({
                    type: 'browser-folder',
                    directoryHandle: selectedDirectoryHandle
                });
            } else {
                // Return empty string for browser download, or the path for server-side save
                resolve(path);
            }
        };

        // Handle cancel
        document.getElementById('export-cancel-btn').onclick = () => {
            document.body.removeChild(overlay);
            resolve(null);
        };

        // Handle ESC key
        overlay.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.body.removeChild(overlay);
                resolve(null);
            }
        });

        // Handle Enter key in input
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('export-confirm-btn').click();
            }
        });
    });
}

/**
 * Get default export path from localStorage or system default
 */
function getDefaultExportPath() {
    return localStorage.getItem('tda_export_directory') || '';
}

/**
 * Import a knowledge repository from a .zip file
 */
export async function importKnowledgeRepository() {
    // Show dialog to choose import method
    const importMode = await showImportModeDialog();
    if (!importMode) {
        return; // User cancelled
    }

    if (importMode === 'file') {
        return importFromFile();
    } else {
        return importFromServerPath();
    }
}

/**
 * Show dialog to choose import method
 */
async function showImportModeDialog() {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';

        const modal = document.createElement('div');
        modal.className = 'bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4';
        modal.innerHTML = `
            <h3 class="text-xl font-semibold text-white mb-4">Import Collection</h3>
            <p class="text-gray-300 mb-6">Choose how you want to import the collection:</p>

            <div class="space-y-3 mb-6">
                <button
                    id="import-from-file-btn"
                    class="w-full px-4 py-3 rounded-md bg-blue-600 hover:bg-blue-500 text-white text-left transition-colors flex items-center"
                >
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
                    </svg>
                    <div>
                        <div class="font-semibold">Upload from Computer</div>
                        <div class="text-sm text-gray-300">Select a .zip file from your local machine</div>
                    </div>
                </button>

                <button
                    id="import-from-path-btn"
                    class="w-full px-4 py-3 rounded-md bg-gray-700 hover:bg-gray-600 text-white text-left transition-colors flex items-center"
                >
                    <svg class="w-5 h-5 mr-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z"/>
                    </svg>
                    <div>
                        <div class="font-semibold">Import from Server Path</div>
                        <div class="text-sm text-gray-300">Specify a file path on the server</div>
                    </div>
                </button>
            </div>

            <div class="flex justify-end">
                <button
                    id="import-cancel-btn"
                    class="px-4 py-2 rounded-md bg-gray-600 hover:bg-gray-500 text-white transition-colors"
                >
                    Cancel
                </button>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        // Handle file upload
        document.getElementById('import-from-file-btn').onclick = () => {
            document.body.removeChild(overlay);
            resolve('file');
        };

        // Handle server path
        document.getElementById('import-from-path-btn').onclick = () => {
            document.body.removeChild(overlay);
            resolve('path');
        };

        // Handle cancel
        document.getElementById('import-cancel-btn').onclick = () => {
            document.body.removeChild(overlay);
            resolve(null);
        };

        // Handle ESC key
        overlay.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.body.removeChild(overlay);
                resolve(null);
            }
        });
    });
}

/**
 * Import from file upload
 */
async function importFromFile() {
    return new Promise((resolve, reject) => {
        // Create file input
        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.accept = '.zip';

        fileInput.onchange = async (e) => {
            const file = e.target.files[0];
            if (!file) {
                reject(new Error('No file selected'));
                return;
            }

            try {
                console.log('[Knowledge] Importing collection from:', file.name);

                // Show progress banner
                if (window.showAppBanner) {
                    window.showAppBanner(`Importing collection from ${file.name}...`, 'info');
                }

                const formData = new FormData();
                formData.append('file', file);

                const token = localStorage.getItem('tda_auth_token');
                const response = await fetch('/api/v1/rag/collections/import', {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${token}`
                    },
                    body: formData
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.message || 'Import failed');
                }

                const result = await response.json();
                console.log('[Knowledge] Import successful:', result);

                if (window.showAppBanner) {
                    window.showAppBanner(
                        `Collection "${result.collection_name}" imported successfully (${result.document_count} documents)!`,
                        'success'
                    );
                }

                // Reload collections
                await reloadCollections();

                resolve(result);

            } catch (error) {
                console.error('[Knowledge] Import error:', error);
                if (window.showAppBanner) {
                    window.showAppBanner(`Import failed: ${error.message}`, 'error');
                }
                reject(error);
            }
        };

        // Trigger file selection
        fileInput.click();
    });
}

/**
 * Import from server path
 */
async function importFromServerPath() {
    const importPath = await showImportPathDialog();
    if (!importPath) {
        return; // User cancelled
    }

    try {
        console.log('[Knowledge] Importing from server path:', importPath);

        // Show progress banner
        if (window.showAppBanner) {
            window.showAppBanner(`Importing collection from ${importPath}...`, 'info');
        }

        const token = localStorage.getItem('tda_auth_token');
        const response = await fetch('/api/v1/rag/collections/import', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                import_path: importPath
            })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || 'Import failed');
        }

        const result = await response.json();
        console.log('[Knowledge] Import successful:', result);

        if (window.showAppBanner) {
            window.showAppBanner(
                `Collection "${result.collection_name}" imported successfully (${result.document_count} documents)!`,
                'success'
            );
        }

        // Reload collections
        await reloadCollections();

        return result;

    } catch (error) {
        console.error('[Knowledge] Import error:', error);
        if (window.showAppBanner) {
            window.showAppBanner(`Import failed: ${error.message}`, 'error');
        }
        throw error;
    }
}

/**
 * Show dialog for server path input
 */
async function showImportPathDialog() {
    return new Promise((resolve) => {
        const overlay = document.createElement('div');
        overlay.className = 'fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50';

        const modal = document.createElement('div');
        modal.className = 'bg-gray-800 rounded-lg shadow-xl p-6 max-w-md w-full mx-4';
        modal.innerHTML = `
            <h3 class="text-xl font-semibold text-white mb-4">Import from Server Path</h3>
            <p class="text-gray-300 mb-4">Enter the full path to the .zip file on the server:</p>

            <div class="mb-6">
                <label class="block text-sm font-medium text-gray-300 mb-2">Import File Path</label>
                <input
                    type="text"
                    id="import-path-input"
                    class="w-full px-3 py-2 bg-gray-700 border border-gray-600 rounded-md text-white placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="/path/to/collection.zip"
                    value="${getDefaultImportPath()}"
                />
                <p class="text-xs text-gray-400 mt-2">
                    Example: /exports/collection_3_MyCollection.zip
                </p>
            </div>

            <div class="flex justify-end space-x-3">
                <button
                    id="import-path-cancel-btn"
                    class="px-4 py-2 rounded-md bg-gray-600 hover:bg-gray-500 text-white transition-colors"
                >
                    Cancel
                </button>
                <button
                    id="import-path-confirm-btn"
                    class="px-4 py-2 rounded-md bg-blue-600 hover:bg-blue-500 text-white transition-colors"
                >
                    Import
                </button>
            </div>
        `;

        overlay.appendChild(modal);
        document.body.appendChild(overlay);

        const input = document.getElementById('import-path-input');
        setTimeout(() => input.focus(), 100);

        // Handle confirm
        document.getElementById('import-path-confirm-btn').onclick = () => {
            const path = input.value.trim();
            if (path) {
                localStorage.setItem('tda_import_directory', path);
            }
            document.body.removeChild(overlay);
            resolve(path || null);
        };

        // Handle cancel
        document.getElementById('import-path-cancel-btn').onclick = () => {
            document.body.removeChild(overlay);
            resolve(null);
        };

        // Handle ESC key
        overlay.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                document.body.removeChild(overlay);
                resolve(null);
            }
        });

        // Handle Enter key
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('import-path-confirm-btn').click();
            }
        });
    });
}

/**
 * Get default import path from localStorage
 */
function getDefaultImportPath() {
    return localStorage.getItem('tda_import_directory') || '';
}

/**
 * Reload both knowledge and planner collections
 */
async function reloadCollections() {
    // Reload knowledge repositories
    if (typeof loadKnowledgeRepositories === 'function') {
        await loadKnowledgeRepositories();
    }

    // Reload planner repositories using the correct function
    await loadRagCollections();
}
