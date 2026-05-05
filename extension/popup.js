const btn = document.getElementById("syncBtn");
const status = document.getElementById("status");

function showLastSync() {
  chrome.storage.local.get(["lastSync", "lastStats"], (data) => {
    if (data.lastSync) {
      const d = new Date(data.lastSync);
      status.textContent = `Last sync: ${d.toLocaleString()}`;
    } else {
      status.textContent = "Not yet synced.";
    }
  });
}

btn.addEventListener("click", async () => {
  btn.disabled = true;
  btn.textContent = "Syncing\u2026";
  status.textContent = "";
  try {
    await performSync();
    showLastSync();
  } catch (e) {
    status.textContent = `Error: ${e.message}`;
  } finally {
    btn.disabled = false;
    btn.textContent = "Sync Now";
  }
});

showLastSync();
