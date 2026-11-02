package com.personal.harmaai.data

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Transaction
import androidx.room.Update
import kotlinx.coroutines.flow.Flow

@Dao
interface TaskDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(task: TaskEntity)

    @Update
    suspend fun update(task: TaskEntity)

    @Query(
        "UPDATE agent_tasks SET status = :status, summary = :summary, endedAt = :endedAt " +
            "WHERE id = :taskId",
    )
    suspend fun finish(taskId: String, status: String, summary: String?, endedAt: Long)

    @Query("SELECT * FROM agent_tasks WHERE id = :taskId LIMIT 1")
    suspend fun get(taskId: String): TaskEntity?

    @Query("SELECT * FROM agent_tasks ORDER BY startedAt DESC LIMIT :limit")
    fun observeRecent(limit: Int = 100): Flow<List<TaskEntity>>

    @Transaction
    @Query("SELECT * FROM agent_tasks WHERE id = :taskId LIMIT 1")
    fun observeWithSteps(taskId: String): Flow<TaskWithSteps?>

    @Query("DELETE FROM agent_tasks WHERE startedAt < :olderThan")
    suspend fun deleteOlderThan(olderThan: Long): Int
}

@Dao
interface StepDao {
    @Insert
    suspend fun insert(step: StepEntity): Long

    @Insert
    suspend fun insertAll(steps: List<StepEntity>): List<Long>

    @Query("SELECT * FROM agent_steps WHERE taskId = :taskId ORDER BY stepNumber ASC, id ASC")
    fun observeForTask(taskId: String): Flow<List<StepEntity>>

    @Query("SELECT * FROM agent_steps ORDER BY createdAt DESC LIMIT :limit")
    fun observeRecent(limit: Int = 200): Flow<List<StepEntity>>
}

@Dao
interface MemoryDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(memory: MemoryEntity): Long

    @Query("SELECT * FROM agent_memories WHERE memoryKey = :key LIMIT 1")
    suspend fun getByKey(key: String): MemoryEntity?

    @Query(
        "SELECT * FROM agent_memories " +
            "ORDER BY importance DESC, confidence DESC, updatedAt DESC LIMIT :limit",
    )
    suspend fun getRelevant(limit: Int = 20): List<MemoryEntity>

    @Query("SELECT * FROM agent_memories ORDER BY updatedAt DESC")
    fun observeAll(): Flow<List<MemoryEntity>>

    @Query("DELETE FROM agent_memories WHERE memoryKey = :key")
    suspend fun deleteByKey(key: String)

    @Query("DELETE FROM agent_memories")
    suspend fun clear()
}

@Dao
interface QueuedTaskDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(task: QueuedTaskEntity)

    @Query(
        "SELECT * FROM offline_task_queue " +
            "WHERE status = 'PENDING' AND expiresAt > :now " +
            "ORDER BY createdAt ASC",
    )
    suspend fun getPendingValid(now: Long = System.currentTimeMillis()): List<QueuedTaskEntity>

    @Query(
        "SELECT * FROM offline_task_queue " +
            "WHERE status = 'PENDING' AND LOWER(command) = LOWER(:command) LIMIT 1",
    )
    suspend fun findDuplicatePending(command: String): QueuedTaskEntity?

    @Query(
        "UPDATE offline_task_queue SET status = :status, retryCount = :retryCount WHERE id = :id",
    )
    suspend fun updateStatus(id: String, status: String, retryCount: Int)

    @Query(
        "UPDATE offline_task_queue SET status = 'EXPIRED' WHERE status = 'PENDING' AND expiresAt <= :now",
    )
    suspend fun expireStale(now: Long = System.currentTimeMillis()): Int

    @Query("UPDATE offline_task_queue SET status = 'CANCELLED' WHERE status = 'PENDING'")
    suspend fun cancelAllPending()

    @Query("SELECT * FROM offline_task_queue WHERE status = 'PENDING' ORDER BY createdAt ASC")
    fun observePending(): Flow<List<QueuedTaskEntity>>
}

@Dao
interface LearnedMacroDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun upsert(macro: LearnedMacroEntity)

    @Query("SELECT * FROM learned_ui_macros WHERE normalizedCommand = :normalizedCommand LIMIT 1")
    suspend fun findByNormalizedCommand(normalizedCommand: String): LearnedMacroEntity?

    @Query("SELECT * FROM learned_ui_macros ORDER BY successCount DESC, updatedAt DESC LIMIT :limit")
    suspend fun getRecent(limit: Int = 50): List<LearnedMacroEntity>

    @Query(
        "UPDATE learned_ui_macros " +
            "SET successCount = successCount + 1, failureCount = 0, updatedAt = :now " +
            "WHERE normalizedCommand = :normalizedCommand",
    )
    suspend fun recordReplaySuccess(
        normalizedCommand: String,
        now: Long = System.currentTimeMillis(),
    )

    @Query(
        "UPDATE learned_ui_macros " +
            "SET failureCount = failureCount + 1, updatedAt = :now " +
            "WHERE normalizedCommand = :normalizedCommand",
    )
    suspend fun recordReplayFailure(
        normalizedCommand: String,
        now: Long = System.currentTimeMillis(),
    )

    @Query("DELETE FROM learned_ui_macros WHERE normalizedCommand = :normalizedCommand")
    suspend fun deleteByNormalizedCommand(normalizedCommand: String)
}

