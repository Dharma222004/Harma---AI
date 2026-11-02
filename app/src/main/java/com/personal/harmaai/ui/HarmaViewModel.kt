package com.personal.harmaai.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import com.personal.harmaai.HarmaAiApplication
import com.personal.harmaai.agent.AgentRuntime
import com.personal.harmaai.agent.AgentStatus
import com.personal.harmaai.data.TaskEntity
import com.personal.harmaai.service.HarmaAgentService
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.stateIn

class HarmaViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as HarmaAiApplication
    val runtime = AgentRuntime.state
    val settings get() = app.settings

    val recentTasks: StateFlow<List<TaskEntity>> = app.database.taskDao()
        .observeRecent(100)
        .stateIn(viewModelScope, SharingStarted.WhileSubscribed(5_000), emptyList())

    fun submit(command: String) {
        if (command.isBlank()) return
        val status = runtime.value.status
        if (status == AgentStatus.RUNNING || status == AgentStatus.WAITING_FOR_CONFIRMATION) return
        HarmaAgentService.startTask(getApplication(), command.trim())
    }

    fun stop() = HarmaAgentService.stopTask(getApplication())

    fun confirm(approved: Boolean) = AgentRuntime.respondToConfirmation(approved)
}
