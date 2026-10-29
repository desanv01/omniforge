cmake_minimum_required(VERSION 3.25)
project(omniforge_inert_probe_supervisor LANGUAGES C)
if(NOT WIN32 OR NOT MSVC OR NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
  message(FATAL_ERROR "Reviewed MSVC Windows x64 only")
endif()
set(OF_EXPECTED_VS_INSTANCE "" CACHE PATH "Explicit approved VS2022 BuildTools instance")
if(NOT CMAKE_GENERATOR STREQUAL "Visual Studio 17 2022" OR
   NOT CMAKE_GENERATOR_PLATFORM STREQUAL "x64" OR
   NOT MSVC_TOOLSET_VERSION STREQUAL "143" OR
   NOT CMAKE_VS_PLATFORM_TOOLSET STREQUAL "v143" OR
   NOT CMAKE_GENERATOR_TOOLSET STREQUAL "v143,version=14.44.35207")
  message(FATAL_ERROR "Explicit VS2022 x64 v143,version=14.44.35207 required")
endif()
if(NOT IS_ABSOLUTE "${OF_EXPECTED_VS_INSTANCE}" OR
   NOT IS_DIRECTORY "${OF_EXPECTED_VS_INSTANCE}" OR
   NOT IS_ABSOLUTE "${CMAKE_GENERATOR_INSTANCE}" OR
   NOT IS_DIRECTORY "${CMAKE_GENERATOR_INSTANCE}")
  message(FATAL_ERROR "Supply explicit expected and generator instance paths")
endif()
file(REAL_PATH "${OF_EXPECTED_VS_INSTANCE}" _sup_expected)
file(REAL_PATH "${CMAKE_GENERATOR_INSTANCE}" _sup_selected)
cmake_path(CONVERT "${_sup_expected}" TO_CMAKE_PATH_LIST _sup_expected NORMALIZE)
cmake_path(CONVERT "${_sup_selected}" TO_CMAKE_PATH_LIST _sup_selected NORMALIZE)
string(TOLOWER "${_sup_expected}" _sup_expected)
string(TOLOWER "${_sup_selected}" _sup_selected)
if(NOT _sup_expected MATCHES "/2022/buildtools$" OR NOT _sup_selected STREQUAL _sup_expected)
  message(FATAL_ERROR "Selected instance differs from explicit approved BuildTools")
endif()
foreach(_sup_variable IN ITEMS CMAKE_C_COMPILER CMAKE_C_COMPILER_LINKER CMAKE_LINKER)
  if(_sup_variable STREQUAL "CMAKE_C_COMPILER")
    set(_sup_executable "cl.exe")
  else()
    set(_sup_executable "link.exe")
  endif()
  if(NOT DEFINED ${_sup_variable} OR NOT IS_ABSOLUTE "${${_sup_variable}}" OR NOT EXISTS "${${_sup_variable}}")
    message(FATAL_ERROR "Missing explicit selected tool: ${_sup_variable}")
  endif()
  file(REAL_PATH "${${_sup_variable}}" _sup_actual)
  cmake_path(CONVERT "${_sup_actual}" TO_CMAKE_PATH_LIST _sup_actual NORMALIZE)
  string(TOLOWER "${_sup_actual}" _sup_actual)
  set(_sup_wanted "${_sup_expected}/vc/tools/msvc/14.44.35207/bin/hostx64/x64/${_sup_executable}")
  if(NOT _sup_actual STREQUAL _sup_wanted)
    message(FATAL_ERROR "Selected tool is outside reviewed x64 toolset")
  endif()
endforeach()
if(NOT CMAKE_SYSTEM_VERSION STREQUAL "10.0.26100.0" OR
   NOT CMAKE_VS_WINDOWS_TARGET_PLATFORM_VERSION STREQUAL "10.0.26100.0")
  message(FATAL_ERROR "Reviewed Windows SDK 10.0.26100.0 required")
endif()
get_filename_component(_sup_root "${CMAKE_CURRENT_SOURCE_DIR}/../../../.." ABSOLUTE)
add_executable(inert_probe_supervisor "${_sup_root}/tests/contracts/providers/native/inert_probe_supervisor.c")
add_executable(inert_probe_supervisor_model "${_sup_root}/tests/contracts/providers/native/test_inert_probe_supervisor.c")
foreach(_sup_target IN ITEMS inert_probe_supervisor inert_probe_supervisor_model)
  set_property(TARGET ${_sup_target} PROPERTY C_STANDARD 11)
  set_property(TARGET ${_sup_target} PROPERTY C_STANDARD_REQUIRED ON)
  set_property(TARGET ${_sup_target} PROPERTY MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
  target_compile_definitions(${_sup_target} PRIVATE _WIN32_WINNT=0x0A00 UNICODE _UNICODE)
  target_compile_options(${_sup_target} PRIVATE /W4 /WX /guard:cf)
  target_link_options(${_sup_target} PRIVATE /guard:cf)
endforeach()
target_link_libraries(inert_probe_supervisor PRIVATE bcrypt advapi32)
# Model includes the common state machine under SP_MODEL; native adapter/wmain
# are excluded by preprocessor; no adapter, target implementation or import library
# is linked. Static CRT system imports still require actual binary inspection.
# No CTest, custom command, post-build execution, target DLL/probe/library linkage.
# Building either target NEVER authorizes running the native supervisor or probe.
