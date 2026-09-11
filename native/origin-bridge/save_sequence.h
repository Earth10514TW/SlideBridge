#pragma once

// Small, platform-independent representation of the persistence ordering used
// by the OLE host.  Keeping the ordering here makes failure cleanup testable
// without activating Origin or requiring a compound-file fixture.
template <typename Result, typename IsSuccess, typename GetClassId,
          typename WriteClass, typename Save, typename Commit, typename Complete,
          typename CompletionFailure>
Result RunPersistenceSave(IsSuccess isSuccess, GetClassId getClassId,
                          WriteClass writeClass, Save save, Commit commit,
                          Complete complete, bool& poisoned,
                          CompletionFailure completionFailure, Result poisonedResult) {
  if (poisoned) {
    return poisonedResult;
  }
  Result result = getClassId();
  bool saveInvoked = false;
  if (isSuccess(result)) {
    result = writeClass();
  }
  if (isSuccess(result)) {
    saveInvoked = true;
    result = save();
    if (isSuccess(result)) {
      result = commit();
    }
  }
  if (saveInvoked) {
    Result completionResult = complete();
    if (!isSuccess(completionResult)) {
      if (isSuccess(result)) {
        result = completionResult;
      }
      poisoned = true;
      completionFailure(completionResult);
    }
  }
  return result;
}
