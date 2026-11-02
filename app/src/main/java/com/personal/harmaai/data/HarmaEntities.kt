package com.personal.harmaai.data

import androidx.room.Entity
import androidx.room.ForeignKey
import androidx.room.Index
import androidx.room.PrimaryKey

@Entity(tableName = "agent_tasks")
data class TaskEntity(
    @PrimaryKey val id: String,
    val command: String,
    val status: String,
    val summary: String? = null,
    val startedAt: Long = System.currentTimeMillis(),
    val endedAt: Long? = null,
)

@Entity(
    tableName = "agent_steps",
    foreignKeys = [
        ForeignKey(
            entity = TaskEntity::class,
            parentColumns = ["id"],
            childColumns = ["taskId"],
            onDelete = ForeignKey.CASCADE,
        ),
    ],
    indices = [Index("taskId"), Index(value = ["taskId", "stepNumber"])],
)
data class StepEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val taskId: String,
    val stepNumber: Int,
    val category: String,
    val toolName: String? = null,
    val argumentsJson: String? = null,
    val result: String,
    val success: Boolean? = null,
    val screenshotPath: String? = null,
    val createdAt: Long = System.currentTimeMillis(),
)

@Entity(
    tableName = "agent_memories",
    indices = [Index(value = ["memoryKey"], unique = true), Index("updatedAt")],
)
data class MemoryEntity(
    @PrimaryKey(autoGenerate = true) val id: Long = 0,
    val memoryKey: String,
    val value: String,
    val importance: Int = 1,
    val confidence: Float = 1f,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
)

@Entity(
    tableName = "offline_task_queue",
    indices = [Index("status"), Index("createdAt")],
)
data class QueuedTaskEntity(
    @PrimaryKey val id: String,
    val command: String,
    val status: String = STATUS_PENDING,
    val retryCount: Int = 0,
    val isSensitive: Boolean = false,
    val createdAt: Long = System.currentTimeMillis(),
    val expiresAt: Long = System.currentTimeMillis() + DEFAULT_TTL_MS,
) {
    companion object {
        const val STATUS_PENDING = "PENDING"
        const val STATUS_RUNNING = "RUNNING"
        const val STATUS_COMPLETED = "COMPLETED"
        const val STATUS_EXPIRED = "EXPIRED"
        const val STATUS_CANCELLED = "CANCELLED"
        const val STATUS_FAILED = "FAILED"
        const val DEFAULT_TTL_MS = 6 * 60 * 60 * 1000L
    }
}

@Entity(
    tableName = "learned_ui_macros",
    indices = [Index("targetPackage"), Index("updatedAt")],
)
data class LearnedMacroEntity(
    @PrimaryKey val normalizedCommand: String,
    val rawCommand: String,
    val targetPackage: String,
    val stepsJson: String,
    val finalSummary: String,
    val successCount: Int = 1,
    val failureCount: Int = 0,
    val createdAt: Long = System.currentTimeMillis(),
    val updatedAt: Long = System.currentTimeMillis(),
)

data class TaskWithSteps(
    @androidx.room.Embedded val task: TaskEntity,
    @androidx.room.Relation(
        parentColumn = "id",
        entityColumn = "taskId",
    )
    val steps: List<StepEntity>,
)
