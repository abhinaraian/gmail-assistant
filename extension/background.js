// Enable the side panel only when the user is on Gmail
chrome.tabs.onUpdated.addListener(async (tabId, info, tab) => {
  if (!tab.url) return;
  const onGmail = tab.url.startsWith("https://mail.google.com");
  await chrome.sidePanel.setOptions({
    tabId,
    path: "panel.html",
    enabled: onGmail,
  });
});

// Open the side panel when the extension icon is clicked
chrome.action.onClicked.addListener(async (tab) => {
  await chrome.sidePanel.open({ tabId: tab.id });
});
