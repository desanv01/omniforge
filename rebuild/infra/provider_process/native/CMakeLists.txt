cmake_minimum_required(VERSION 3.25)
project(omniforge_owned_slot_inert LANGUAGES C)
if(NOT WIN32 OR NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Only MSVC Windows x64 source/harness target is supported")
endif()
set(OF_EXPECTED_VS_INSTANCE "" CACHE PATH "Explicit approved VS2022 BuildTools instance; no discovery fallback")
if(NOT CMAKE_GENERATOR STREQUAL "Visual Studio 17 2022" OR
   NOT CMAKE_GENERATOR_PLATFORM STREQUAL "x64" OR
   NOT MSVC_TOOLSET_VERSION STREQUAL "143" OR
   NOT CMAKE_VS_PLATFORM_TOOLSET STREQUAL "v143" OR
   NOT CMAKE_GENERATOR_TOOLSET STREQUAL "v143,version=14.44.35207")
  message(FATAL_ERROR "Explicit VS2022 x64 v143,version=14.44.35207 selection required")
endif()
if(NOT IS_ABSOLUTE "${OF_EXPECTED_VS_INSTANCE}" OR
   NOT IS_DIRECTORY "${OF_EXPECTED_VS_INSTANCE}" OR
   NOT IS_ABSOLUTE "${CMAKE_GENERATOR_INSTANCE}" OR
   NOT IS_DIRECTORY "${CMAKE_GENERATOR_INSTANCE}")
  message(FATAL_ERROR "Supply both OF_EXPECTED_VS_INSTANCE and the explicit generator instance")
endif()
file(REAL_PATH "${OF_EXPECTED_VS_INSTANCE}" _slot_expected_instance)
file(REAL_PATH "${CMAKE_GENERATOR_INSTANCE}" _slot_selected_instance)
cmake_path(CONVERT "${_slot_expected_instance}" TO_CMAKE_PATH_LIST _slot_expected_instance NORMALIZE)
cmake_path(CONVERT "${_slot_selected_instance}" TO_CMAKE_PATH_LIST _slot_selected_instance NORMALIZE)
string(TOLOWER "${_slot_expected_instance}" _slot_expected_instance)
string(TOLOWER "${_slot_selected_instance}" _slot_selected_instance)
if(NOT _slot_expected_instance MATCHES "/2022/buildtools$" OR
   NOT _slot_selected_instance STREQUAL _slot_expected_instance)
  message(FATAL_ERROR "Selected VS2022 BuildTools instance differs from explicit approved instance")
endif()
# Minor props-file reporting can be empty/converted. Pin the selected executables
# instead; no personal path or ambient compiler/linker fallback is permitted.
foreach(_slot_variable IN ITEMS CMAKE_C_COMPILER CMAKE_C_COMPILER_LINKER CMAKE_LINKER)
  if(_slot_variable STREQUAL "CMAKE_C_COMPILER")
    set(_slot_executable "cl.exe")
  else()
    set(_slot_executable "link.exe")
  endif()
  if(NOT DEFINED ${_slot_variable} OR NOT IS_ABSOLUTE "${${_slot_variable}}" OR
     NOT EXISTS "${${_slot_variable}}")
    message(FATAL_ERROR "Missing explicit selected tool: ${_slot_variable}")
  endif()
  file(REAL_PATH "${${_slot_variable}}" _slot_actual_tool)
  cmake_path(CONVERT "${_slot_actual_tool}" TO_CMAKE_PATH_LIST _slot_actual_tool NORMALIZE)
  string(TOLOWER "${_slot_actual_tool}" _slot_actual_tool)
  set(_slot_expected_tool "${_slot_expected_instance}/vc/tools/msvc/14.44.35207/bin/hostx64/x64/${_slot_executable}")
  if(NOT _slot_actual_tool STREQUAL _slot_expected_tool)
    message(FATAL_ERROR "Selected ${_slot_variable} is outside the exact approved x64 toolset")
  endif()
endforeach()
if(NOT CMAKE_SYSTEM_VERSION STREQUAL "10.0.26100.0" OR
   NOT CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION STREQUAL "10.0.26100.0")
  message(FATAL_ERROR "Select reviewed Windows SDK 10.0.26100.0")
endif()
add_executable(owned_slot_inert
  owned_slot.c
  ../../../tests/contracts/providers/native/test_owned_slot.c)
# Native directory is infra/provider_process/native: source root is ../../..
target_include_directories(owned_slot_inert PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
set_property(TARGET owned_slot_inert PROPERTY C_STANDARD 11)
set_property(TARGET owned_slot_inert PROPERTY C_STANDARD_REQUIRED ON)
set_property(TARGET owned_slot_inert PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
target_compile_definitions(owned_slot_inert PRIVATE _WIN32_WINNT=0x0A00 UNICODE _UNICODE)
target_compile_options(owned_slot_inert PRIVATE /W4 /WX /guard:cf)
enable_testing()
add_test(NAME owned_slot_inert COMMAND owned_slot_inert)
# Explicit inert source targets only; default retains the accepted EXE alone.
option(OF_BUILD_INERT_DLL "Build reviewed C-fake export DLL/harness; separate operation release required" OFF)
if(OF_BUILD_INERT_DLL)
  add_library(owned_slot_inert_exports SHARED owned_slot.c slot_inert_exports.c)
  target_compile_definitions(owned_slot_inert_exports PRIVATE OF_INERT_BUILD)
  # Harness includes the export TU to inspect its PRIVATE guard without test exports.
  add_executable(owned_slot_export_harness owned_slot.c
    ../../../tests/contracts/providers/native/test_slot_inert_exports.c)
  foreach(_slot_target IN ITEMS owned_slot_inert_exports owned_slot_export_harness)
    target_include_directories(${_slot_target} PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
    set_property(TARGET ${_slot_target} PROPERTY C_STANDARD 11)
    set_property(TARGET ${_slot_target} PROPERTY C_STANDARD_REQUIRED ON)
    set_property(TARGET ${_slot_target} PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
    target_compile_definitions(${_slot_target} PRIVATE _WIN32_WINNT=0x0A00 UNICODE _UNICODE)
    target_compile_options(${_slot_target} PRIVATE /W4 /WX /guard:cf)
  endforeach()
  add_test(NAME owned_slot_export_harness COMMAND owned_slot_export_harness)
endif()
# No real Win32 table, default loader, install or native ownership runtime target.
