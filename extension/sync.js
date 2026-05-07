// SPDX-License-Identifier: MIT
/**
 * Bookmark tree conversion and diff logic for the Chrome side.
 */

const HOST_NAME = "com.shayelkin.sync_safari_bookmarks";

/**
 * Convert Chrome's bookmark tree (from chrome.bookmarks.getTree) into
 * the canonical format: {bookmark_bar: [...], other: [...]}.
 */
function chromeTreeToCanonical(tree) {
  const roots = tree[0].children;
  const result = {};
  for (const root of roots) {
    switch (root.id) {
      case "1":
        result.bookmark_bar = convertChildren(root.children || []);
        break;
      case "2":
        result.other = convertChildren(root.children || []);
        break;
      // id "3" is mobile bookmarks — ignored.
    }
  }
  return result;
}

function convertChildren(nodes) {
  return nodes.map((node) => {
    if (node.url) {
      return {
        type: "bookmark",
        title: node.title || "",
        url: node.url,
        date: node.dateAdded
          ? new Date(node.dateAdded).toISOString()
          : new Date().toISOString(),
      };
    }
    return {
      type: "folder",
      title: node.title || "",
      children: convertChildren(node.children || []),
    };
  });
}

/**
 * Apply the merged tree from the native host back into Chrome.
 * Strategy: remove all existing bookmarks under the root, then recreate
 * from the merged data. This is simpler and more reliable than computing
 * fine-grained diffs.
 */
async function applyMergedToChrome(merged) {
  const rootMap = { bookmark_bar: "1", other: "2" };
  for (const [key, rootId] of Object.entries(rootMap)) {
    const items = merged[key] || [];
    const existing = await chrome.bookmarks.getChildren(rootId);
    for (const child of existing) {
      await chrome.bookmarks.removeTree(child.id);
    }
    await createChildren(rootId, items);
  }
}

async function createChildren(parentId, items) {
  for (let i = 0; i < items.length; i++) {
    const item = items[i];
    if (item.type === "bookmark") {
      await chrome.bookmarks.create({
        parentId,
        index: i,
        title: item.title,
        url: item.url,
      });
    } else {
      const folder = await chrome.bookmarks.create({
        parentId,
        index: i,
        title: item.title,
      });
      await createChildren(folder.id, item.children || []);
    }
  }
}

/**
 * Perform a full sync: read Chrome tree, send to native host, apply result.
 * Returns {status, stats} from the host response.
 */
async function performSync() {
  const tree = await chrome.bookmarks.getTree();
  const canonical = chromeTreeToCanonical(tree);

  const response = await new Promise((resolve, reject) => {
    chrome.runtime.sendNativeMessage(
      HOST_NAME,
      { action: "sync", chrome_bookmarks: canonical },
      (resp) => {
        if (chrome.runtime.lastError) {
          reject(new Error(chrome.runtime.lastError.message));
          return;
        }
        resolve(resp);
      },
    );
  });

  if (response.status !== "ok") {
    throw new Error(response.error || "unknown error from host");
  }

  await applyMergedToChrome(response.merged);

  await chrome.storage.local.set({
    lastSync: new Date().toISOString(),
    lastStats: response.stats,
  });

  return response;
}
