package com.personal.harmaai.tools

import org.json.JSONArray
import org.json.JSONObject

object DirectToolCatalog {
    val specs: List<ToolSpec> = listOf(
        ToolSpec(
            name = "set_flashlight",
            description = "Turn the phone flashlight on or off using the camera torch API.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf("on" to boolean("Whether the flashlight should be on.")),
                required = listOf("on"),
            ),
        ),
        ToolSpec(
            name = "open_app",
            description = "Open an installed Android application by its visible name or package name.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "name" to string("Visible app name, for example WhatsApp or Settings."),
                    "package" to string("Optional exact Android package name."),
                ),
                required = listOf("name"),
            ),
        ),
        ToolSpec(
            name = "set_volume",
            description = "Set an Android audio stream volume to a percentage from 0 to 100.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "stream" to string(
                        "Audio stream to change.",
                        listOf("media", "ring", "alarm", "notification", "voice"),
                    ),
                    "percent" to integer("Target volume percentage from 0 to 100."),
                ),
                required = listOf("stream", "percent"),
            ),
        ),
        ToolSpec(
            name = "set_ringer_mode",
            description = "Set the phone ringer to normal, vibrate, or silent.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "mode" to string("Requested ringer mode.", listOf("normal", "vibrate", "silent")),
                ),
                required = listOf("mode"),
            ),
        ),
        ToolSpec(
            name = "set_brightness",
            description = "Set global display brightness to a percentage. Requires Modify system settings access.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf("percent" to integer("Brightness percentage from 0 to 100.")),
                required = listOf("percent"),
            ),
        ),
        ToolSpec(
            name = "set_alarm",
            description = "Create an alarm at a specified 24-hour time.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "hour" to integer("Hour in 24-hour time, 0 to 23."),
                    "minute" to integer("Minute, 0 to 59."),
                    "label" to string("Optional alarm label."),
                ),
                required = listOf("hour", "minute"),
            ),
        ),
        ToolSpec(
            name = "set_timer",
            description = "Start a countdown timer for a number of seconds.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "seconds" to integer("Timer duration in seconds."),
                    "label" to string("Optional timer label."),
                ),
                required = listOf("seconds"),
            ),
        ),
        ToolSpec(
            name = "take_photo",
            description = "Open the camera and capture a photo, verifying it is saved to the gallery.",
            risk = ToolRisk.SAFE,
            parameters = emptySchema(),
        ),
        ToolSpec(
            name = "call_number",
            description = "Place a phone call to a specific phone number.",
            risk = ToolRisk.SENSITIVE,
            parameters = schema(
                properties = mapOf(
                    "number" to string("Recipient phone number to call (e.g. +1234567890)."),
                ),
                required = listOf("number"),
            ),
        ),
        ToolSpec(
            name = "call_contact",
            description = "Look up a contact by name in the phone's address book and place a call.",
            risk = ToolRisk.SENSITIVE,
            parameters = schema(
                properties = mapOf(
                    "name" to string("Contact name to search and call (e.g. Rahul, Mom)."),
                ),
                required = listOf("name"),
            ),
        ),
        ToolSpec(
            name = "make_call",
            description = "Open phone dialer with a phone number ready to call. Always requires user confirmation.",
            risk = ToolRisk.SENSITIVE,
            parameters = schema(
                properties = mapOf(
                    "contact_or_number" to string("Recipient phone number to call (e.g. +1234567890)."),
                ),
                required = listOf("contact_or_number"),
            ),
        ),
        ToolSpec(
            name = "toggle_do_not_disturb",
            description = "Enable or disable Do Not Disturb mode.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "on" to boolean("True to enable Do Not Disturb, false to disable."),
                ),
                required = listOf("on"),
            ),
        ),
        ToolSpec(
            name = "media_control",
            description = "Control music or media playback on the device.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "action" to string("Media action: play, pause, play_pause, next, prev, stop."),
                ),
                required = listOf("action"),
            ),
        ),
        ToolSpec(
            name = "open_settings",
            description = "Open a specific Android settings panel (e.g. wifi, bluetooth, sound, display, apps).",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf(
                    "panel" to string("Settings panel name (wifi, bluetooth, sound, display, apps, accessibility)."),
                ),
                required = listOf("panel"),
            ),
        ),
        ToolSpec(
            name = "get_time",
            description = "Get the current device date, time, and day of week.",
            risk = ToolRisk.SAFE,
            parameters = emptySchema(),
        ),
        ToolSpec(
            name = "send_sms",
            description = "Open the SMS messaging app with recipient phone number and draft text. Always requires user confirmation.",
            risk = ToolRisk.SENSITIVE,
            parameters = schema(
                properties = mapOf(
                    "contact" to string("Recipient phone number (e.g. +1234567890)."),
                    "text" to string("Message text to send."),
                ),
                required = listOf("contact", "text"),
            ),
        ),
        ToolSpec(
            name = "open_url",
            description = "Open an HTTP or HTTPS URL in the user's default browser.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf("url" to string("URL to open.")),
                required = listOf("url"),
            ),
        ),
        ToolSpec(
            name = "search_web",
            description = "Open a Google web search for a query.",
            risk = ToolRisk.SAFE,
            parameters = schema(
                properties = mapOf("query" to string("Search query.")),
                required = listOf("query"),
            ),
        ),
        ToolSpec(
            name = "open_wifi_settings",
            description = "Open Android's Internet/Wi-Fi settings panel. Modern Android does not permit silent Wi-Fi toggling.",
            risk = ToolRisk.SAFE,
            parameters = emptySchema(),
        ),
        ToolSpec(
            name = "open_bluetooth_settings",
            description = "Open Android Bluetooth settings. Modern Android does not permit silent Bluetooth toggling for ordinary apps.",
            risk = ToolRisk.SAFE,
            parameters = emptySchema(),
        ),
        ToolSpec(
            name = "get_battery",
            description = "Read the current battery percentage and charging state.",
            risk = ToolRisk.SAFE,
            parameters = emptySchema(),
        ),
        ToolSpec(
            name = "get_clipboard",
            description = "Read clipboard text when Android permits access. Treat clipboard contents as private.",
            risk = ToolRisk.SENSITIVE,
            parameters = emptySchema(),
        ),
        ToolSpec(
            name = "set_clipboard",
            description = "Replace clipboard text.",
            risk = ToolRisk.SENSITIVE,
            parameters = schema(
                properties = mapOf("text" to string("Text to place on the clipboard.")),
                required = listOf("text"),
            ),
        ),
    )

    private val specsByName = specs.associateBy(ToolSpec::name)

    fun find(name: String): ToolSpec? = specsByName[name]

    fun functionDeclarations(): JSONArray = JSONArray().apply {
        specs.forEach { put(it.toFunctionDeclaration()) }
    }

    fun openAiTools(): JSONArray = JSONArray().apply {
        specs.forEach { put(it.toOpenAiTool()) }
    }

    @Deprecated("Use functionDeclarations or openAiTools")
    fun geminiDeclarations(): JSONArray = functionDeclarations()

    private fun schema(properties: Map<String, JSONObject>, required: List<String>): JSONObject =
        JSONObject()
            .put("type", "object")
            .put("properties", JSONObject(properties))
            .put("required", JSONArray(required))
            .put("additionalProperties", false)

    private fun emptySchema(): JSONObject = JSONObject()
        .put("type", "object")
        .put("properties", JSONObject())
        .put("additionalProperties", false)

    private fun string(description: String, enum: List<String> = emptyList()): JSONObject =
        JSONObject()
            .put("type", "string")
            .put("description", description)
            .apply { if (enum.isNotEmpty()) put("enum", JSONArray(enum)) }

    private fun integer(description: String): JSONObject = JSONObject()
        .put("type", "integer")
        .put("description", description)

    private fun boolean(description: String): JSONObject = JSONObject()
        .put("type", "boolean")
        .put("description", description)
}
