#include "save_sequence.h"

// These checks must also run in CMake Release builds.
#ifdef NDEBUG
#undef NDEBUG
#endif
#include <cassert>
#include <string>
#include <vector>

namespace {

struct FakePersistence {
  static constexpr int kOk = 0;
  static constexpr int kSaveFailure = 12;
  static constexpr int kCommitFailure = 13;
  static constexpr int kCompleteFailure = 14;
  static constexpr int kPoisoned = 15;

  int saveResult = kOk;
  int commitResult = kOk;
  int completeResult = kOk;
  std::vector<std::string> calls;

  int ClassId() {
    calls.emplace_back("class");
    return kOk;
  }
  int WriteClass() {
    calls.emplace_back("write");
    return kOk;
  }
  int Save() {
    calls.emplace_back("save");
    return saveResult;
  }
  int Commit() {
    calls.emplace_back("commit");
    return commitResult;
  }
  int Complete() {
    calls.emplace_back("complete");
    return completeResult;
  }
};

int Run(FakePersistence& fake, bool& poisoned) {
  return RunPersistenceSave<int>(
      [](int result) { return result == FakePersistence::kOk; },
      [&] { return fake.ClassId(); }, [&] { return fake.WriteClass(); },
      [&] { return fake.Save(); }, [&] { return fake.Commit(); },
      [&] { return fake.Complete(); }, poisoned, [](int) {}, FakePersistence::kPoisoned);
}

void TestSuccess() {
  FakePersistence fake;
  bool poisoned = false;
  assert(Run(fake, poisoned) == FakePersistence::kOk);
  assert(!poisoned);
  assert((fake.calls == std::vector<std::string>{"class", "write", "save",
                                                  "commit", "complete"}));
}

void TestSaveFailureStillCompletesAndCanRetry() {
  FakePersistence fake;
  fake.saveResult = FakePersistence::kSaveFailure;
  bool poisoned = false;
  assert(Run(fake, poisoned) == FakePersistence::kSaveFailure);
  assert(!poisoned);
  assert((fake.calls == std::vector<std::string>{"class", "write", "save",
                                                  "complete"}));

  fake.saveResult = FakePersistence::kOk;
  fake.calls.clear();
  assert(Run(fake, poisoned) == FakePersistence::kOk);
  assert((fake.calls == std::vector<std::string>{"class", "write", "save",
                                                  "commit", "complete"}));
}

void TestCommitFailureStillCompletes() {
  FakePersistence fake;
  fake.commitResult = FakePersistence::kCommitFailure;
  bool poisoned = false;
  assert(Run(fake, poisoned) == FakePersistence::kCommitFailure);
  assert(!poisoned);
  assert((fake.calls == std::vector<std::string>{"class", "write", "save",
                                                  "commit", "complete"}));
}

void TestCompletionFailurePoisonsAndBlocksRetry() {
  FakePersistence fake;
  fake.completeResult = FakePersistence::kCompleteFailure;
  bool poisoned = false;
  assert(Run(fake, poisoned) == FakePersistence::kCompleteFailure);
  assert(poisoned);
  const auto callsAfterFailure = fake.calls.size();
  assert(Run(fake, poisoned) == FakePersistence::kPoisoned);
  assert(fake.calls.size() == callsAfterFailure);
}

}  // namespace

int main() {
  TestSuccess();
  TestSaveFailureStillCompletesAndCanRetry();
  TestCommitFailureStillCompletes();
  TestCompletionFailurePoisonsAndBlocksRetry();
  return 0;
}
