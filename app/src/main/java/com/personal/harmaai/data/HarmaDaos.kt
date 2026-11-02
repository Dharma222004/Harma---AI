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
