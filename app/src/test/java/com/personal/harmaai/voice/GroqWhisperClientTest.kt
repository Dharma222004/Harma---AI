package com.personal.harmaai.voice

import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class GroqWhisperClientTest {
    @get:Rule
    val tempFolder = TemporaryFolder()

    private val client = GroqWhisperClient()

    @Test
    fun `transcribe fails gracefully when apiKey is blank`() = runBlocking {
        val testFile = tempFolder.newFile("test.m4a").apply {
            writeBytes(ByteArray(100) { 1 })
        }
        val result = client.transcribe(testFile, apiKey = "   ")
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()?.message?.contains("Groq API key is missing") == true)
    }

    @Test
    fun `transcribe fails gracefully when audio file is empty`() = runBlocking {
        val emptyFile = tempFolder.newFile("empty.m4a")
        val result = client.transcribe(emptyFile, apiKey = "gsk_test_12345")
        assertTrue(result.isFailure)
        assertTrue(result.exceptionOrNull()?.message?.contains("empty") == true)
    }

    @Test
    fun `default whisper model is whisper-large-v3-turbo`() {
        assertEquals("whisper-large-v3-turbo", GroqWhisperClient.DEFAULT_MODEL)
    }
}

