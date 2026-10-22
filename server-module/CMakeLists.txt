CollectSourceFiles("${CMAKE_CURRENT_SOURCE_DIR}/src" CONTEXT_SOURCES)
set(CONTEXT_PLAYERBOTS_REVISION "unavailable")
if(EXISTS "${CMAKE_SOURCE_DIR}/modules/mod-playerbots/.git")
  execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${CMAKE_SOURCE_DIR}/modules/mod-playerbots" describe --always --dirty
    OUTPUT_VARIABLE CONTEXT_PLAYERBOTS_REVISION OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET
    RESULT_VARIABLE CONTEXT_GIT_RESULT)
  if(NOT CONTEXT_GIT_RESULT EQUAL 0 OR NOT CONTEXT_PLAYERBOTS_REVISION)
    set(CONTEXT_PLAYERBOTS_REVISION "unavailable")
  endif()
endif()
configure_file("${CMAKE_CURRENT_SOURCE_DIR}/ContextBuild.h.in" "${CMAKE_CURRENT_BINARY_DIR}/ContextBuild.h" @ONLY)
tc_register_module(
  NAME mod-context-api
  SOURCES ${CONTEXT_SOURCES}
  INCLUDE_DIRS "${CMAKE_CURRENT_SOURCE_DIR}/src" "${CMAKE_CURRENT_BINARY_DIR}"
  TEST_SOURCES "${CMAKE_CURRENT_SOURCE_DIR}/tests/test-ContextCache.cpp"
  TEST_LIBRARIES game-interface
  LOADER AddSC_context_api
  CONFIG "${CMAKE_CURRENT_SOURCE_DIR}/conf/context-api.conf.dist")
