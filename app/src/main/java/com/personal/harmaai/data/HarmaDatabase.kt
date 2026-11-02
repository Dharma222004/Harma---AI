package com.personal.harmaai.data

import android.content.Context
import androidx.room.Database
import androidx.room.Room
import androidx.room.RoomDatabase

@Database(
    entities = [
        TaskEntity::class,
        StepEntity::class,
        MemoryEntity::class,
        QueuedTaskEntity::class,
        LearnedMacroEntity::class,
    ],
    version = 3,
    exportSchema = false,
)
abstract class HarmaDatabase : RoomDatabase() {
    abstract fun taskDao(): TaskDao
    abstract fun stepDao(): StepDao
    abstract fun memoryDao(): MemoryDao
    abstract fun queuedTaskDao(): QueuedTaskDao
    abstract fun learnedMacroDao(): LearnedMacroDao

    companion object {
        @Volatile
        private var instance: HarmaDatabase? = null

        fun getInstance(context: Context): HarmaDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                HarmaDatabase::class.java,
                "harma_ai.db",
            ).fallbackToDestructiveMigration().build().also { instance = it }
        }
    }
}
