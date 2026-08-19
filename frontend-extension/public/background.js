const APP_URL = chrome.runtime.getURL("index.html");

async function openApp() {
  const tabs = await chrome.tabs.query({ url: APP_URL });
  const existing = tabs[0];
  if (existing && existing.id != null) {
    await chrome.tabs.update(existing.id, { active: true });
    if (existing.windowId != null) {
      await chrome.windows.update(existing.windowId, { focused: true });
    }
    return;
  }
  await chrome.tabs.create({ url: APP_URL });
}

chrome.action.onClicked.addListener(() => {
  void openApp();
});

chrome.runtime.onInstalled.addListener((details) => {
  if (details.reason === "install") {
    void openApp();
  }
});
