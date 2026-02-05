import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './styles/index.css';

// Mount function for lazy loading from Uderia
window.mountFlowBuilder = function(container, props = {}) {
  const root = ReactDOM.createRoot(container);
  root.render(
    <React.StrictMode>
      <App {...props} />
    </React.StrictMode>
  );
  return root;
};

// Auto-mount if running standalone
const rootElement = document.getElementById('flow-builder-root');
if (rootElement) {
  // Check if JWT token is available (from Uderia)
  const jwtToken = window.uderiaJwtToken || localStorage.getItem('jwtToken');
  const uderiaUrl = window.uderiaBaseUrl || 'http://localhost:5050';
  const flowBuilderUrl = window.flowBuilderBaseUrl || 'http://localhost:5051';

  window.mountFlowBuilder(rootElement, {
    jwtToken,
    uderiaUrl,
    flowBuilderUrl
  });
}
