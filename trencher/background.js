// Clicking the toolbar icon opens the side panel. Nothing else runs in the background.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
