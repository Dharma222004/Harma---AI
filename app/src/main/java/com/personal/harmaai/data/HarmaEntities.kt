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

data class TaskWithSteps(
    @androidx.room.Embedded val task: TaskEntity,
    @androidx.room.Relation(
        parentColumn = "id",
        entityColumn = "taskId",
    )
    val steps: List<StepEntity>,
)
