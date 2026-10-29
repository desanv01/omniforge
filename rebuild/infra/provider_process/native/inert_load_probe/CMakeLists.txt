cmake_minimum_required(VERSION 3.25)
project(omniforge_inert_load_probe LANGUAGES C)
if(NOT WIN32 OR NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Only reviewed MSVC Windows x64 probe is supported")
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
  message(FATAL_ERROR "Supply both expected and generator instance paths")
endif()
file(REAL_PATH "${OF_EXPECTED_VS_INSTANCE}" _probe_expected_instance)
file(REAL_PATH "${CMAKE_GENERATOR_INSTANCE}" _probe_selected_instance)
cmake_path(CONVERT "${_probe_expected_instance}" TO_CMAKE_PATH_LIST _probe_expected_instance NORMALIZE)
cmake_path(CONVERT "${_probe_selected_instance}" TO_CMAKE_PATH_LIST _probe_selected_instance NORMALIZE)
string(TOLOWER "${_probe_expected_instance}" _probe_expected_instance)
string(TOLOWER "${_probe_selected_instance}" _probe_selected_instance)
if(NOT _probe_expected_instance MATCHES "/2022/buildtools$" OR
   NOT _probe_selected_instance STREQUAL _probe_expected_instance)
  message(FATAL_ERROR "Selected instance differs from explicit approved BuildTools")
endif()
foreach(_probe_variable IN ITEMS CMAKE_C_COMPILER CMAKE_C_COMPILER_LINKER CMAKE_LINKER)
  if(_probe_variable STREQUAL "CMAKE_C_COMPILER")
    set(_probe_executable "cl.exe")
  else()
    set(_probe_executable "link.exe")
  endif()
  if(NOT DEFINED ${_probe_variable} OR NOT IS_ABSOLUTE "${${_probe_variable}}" OR
     NOT EXISTS "${${_probe_variable}}")
    message(FATAL_ERROR "Missing explicit selected tool: ${_probe_variable}")
  endif()
  file(REAL_PATH "${${_probe_variable}}" _probe_actual_tool)
  cmake_path(CONVERT "${_probe_actual_tool}" TO_CMAKE_PATH_LIST _probe_actual_tool NORMALIZE)
  string(TOLOWER "${_probe_actual_tool}" _probe_actual_tool)
  set(_probe_expected_tool "${_probe_expected_instance}/vc/tools/msvc/14.44.35207/bin/hostx64/x64/${_probe_executable}")
  if(NOT _probe_actual_tool STREQUAL _probe_expected_tool)
    message(FATAL_ERROR "Selected ${_probe_variable} is outside reviewed x64 toolset")
  endif()
endforeach()
if(NOT CMAKE_SYSTEM_VERSION STREQUAL "10.0.26100.0" OR
   NOT CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION STREQUAL "10.0.26100.0")
  message(FATAL_ERROR "Select reviewed Windows SDK 10.0.26100.0")
endif()
get_filename_component(_probe_root "${CMAKE_CURRENT_SOURCE_DIR}/../../../.." ABSOLUTE)
add_executable(inert_load_probe "${_probe_root}/tests/contracts/providers/native/inert_load_probe.c")
target_include_directories(inert_load_probe PRIVATE "${_probe_root}/infra/provider_process/native")
set_property(TARGET inert_load_probe PROPERTY C_STANDARD 11)
set_property(TARGET inert_load_probe PROPERTY C_STANDARD_REQUIRED ON)
set_property(TARGET inert_load_probe PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
target_compile_definitions(inert_load_probe PRIVATE _WIN32_WINNT=0x0A00 UNICODE _UNICODE)
target_compile_options(inert_load_probe PRIVATE /W4 /WX /guard:cf)
target_link_options(inert_load_probe PRIVATE /guard:cf)
# No target DLL import library/core/wrapper implementation and no CTest auto-load.
# Header declarations alone introduce no direct target references. Default OS SDK
# libraries supply only the probe's own loader/pin/symbol operations.
