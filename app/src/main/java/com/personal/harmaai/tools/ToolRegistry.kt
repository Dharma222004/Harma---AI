package com.personal.harmaai.tools

import android.content.Context
import org.json.JSONObject

class ToolRegistry(context: Context) {
    private val directExecutor = DirectToolExecutor(context)

    val specs: List<ToolSpec> = DirectToolCatalog.specs

    fun find(name: String): ToolSpec? = DirectToolCatalog.find(name)

    suspend fun execute(name: String, args: JSONObject): ToolResult =
        directExecutor.execute(ToolCall(name = name, arguments = args))
}
