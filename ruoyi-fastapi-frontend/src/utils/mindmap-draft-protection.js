/**
 * Track whether the latest local document revision has a confirmed durable
 * draft. Save-status labels describe cloud transport and must never be used as
 * proof that IndexedDB/localStorage actually committed the current revision.
 */
export function createMindmapDraftProtectionTracker() {
  let changeVersion = 0
  let savedVersion = -1
  let state = 'idle'

  const markDirty = () => {
    changeVersion += 1
    state = 'pending'
    return changeVersion
  }

  const beginPersist = () => {
    if (savedVersion < changeVersion) state = 'pending'
    return changeVersion
  }

  const recordPersistResult = (snapshotVersion, saved) => {
    if (!Number.isSafeInteger(snapshotVersion) || snapshotVersion < 0) {
      return state
    }
    if (saved === true) {
      savedVersion = Math.max(savedVersion, snapshotVersion)
      state = savedVersion >= changeVersion ? 'saved' : 'pending'
    } else if (snapshotVersion >= changeVersion && savedVersion < changeVersion) {
      state = 'failed'
    }
    return state
  }

  const markClean = () => {
    savedVersion = changeVersion
    state = 'idle'
  }

  return {
    markDirty,
    beginPersist,
    recordPersistResult,
    markClean,
    isProtected: () => savedVersion >= changeVersion,
    getState: () => state,
    getChangeVersion: () => changeVersion,
    getSavedVersion: () => savedVersion,
  }
}
