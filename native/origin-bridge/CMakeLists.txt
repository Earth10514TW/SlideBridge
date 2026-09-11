cmake_minimum_required(VERSION 3.20)

project(origin_bridge LANGUAGES CXX)

if(NOT WIN32)
  message(FATAL_ERROR "origin-bridge is a Windows OLE host and must be built on Windows")
endif()

add_executable(origin-bridge main.cpp)
target_compile_features(origin-bridge PRIVATE cxx_std_17)
target_compile_definitions(origin-bridge PRIVATE UNICODE _UNICODE NOMINMAX WIN32_LEAN_AND_MEAN)
target_link_libraries(origin-bridge PRIVATE ole32 uuid user32)

# wmain is the Unicode entry point used by both MSVC and MinGW.  Keep the
# MinGW target as a console application so inspect/probe diagnostics remain
# visible in the invoking terminal.
if(MINGW)
  target_link_options(origin-bridge PRIVATE -municode -static-libgcc -static-libstdc++)
endif()

include(CTest)
if(BUILD_TESTING)
  add_executable(origin-bridge-save-test save_sequence_test.cpp)
  target_compile_features(origin-bridge-save-test PRIVATE cxx_std_17)
  add_test(NAME origin-bridge-save-sequence COMMAND origin-bridge-save-test)
endif()
