package ai.harma.app.device

import android.content.Context
import ai.harma.app.data.local.SecurePreferences
import ai.harma.app.data.model.PlanStep
import ai.harma.app.data.model.VerificationState

data class CapabilityExecutionResult(
    val success: Boolean,
    val status: VerificationState,
    val message: String,
    val details: Map<String, Any?> = emptyMap()
)

/**
 * Android Device Capability Dispatcher
 * Bridges Harma Runtime execution plan steps to native Android hardware and software APIs.
 */
class CapabilityDispatcher(
    private val context: Context,
    private val securePrefs: SecurePreferences,
    private val appLauncher: AppLauncher = AppLauncher(context),
    private val flashlightController: FlashlightController = FlashlightController(context),
    private val whatsAppAutomation: WhatsAppAutomation = WhatsAppAutomation(context, appLauncher)
) {

    suspend fun executeStep(
        step: PlanStep,
        stepListener: ((String) -> Unit)? = null
    ): CapabilityExecutionResult {
        return when (step.capability.uppercase()) {
            "APP_LAUNCH" -> executeAppLaunch(step)
            "FLASHLIGHT" -> executeFlashlight(step)
            "WHATSAPP_SEND" -> executeWhatsAppSend(step, stepListener)
            "UI_CLICK" -> executeUiClick(step)
            "TEXT_INPUT" -> executeTextInput(step)
            "BACK" -> executeGlobalAction("BACK")
            "HOME" -> executeGlobalAction("HOME")
            "RECENTS" -> executeGlobalAction("RECENTS")
            else -> CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Unsupported capability: ${step.capability}"
            )
        }
    }

    private fun executeAppLaunch(step: PlanStep): CapabilityExecutionResult {
        val appName = step.parameters["app_name"]?.toString()
        val pkg = step.parameters["package_name"]?.toString()

        val launched = if (!pkg.isNullOrBlank()) {
            appLauncher.launchPackage(pkg)
        } else if (!appName.isNullOrBlank()) {
            appLauncher.launchAppByName(appName)
        } else {
            false
        }

        return if (launched) {
            CapabilityExecutionResult(
                success = true,
                status = VerificationState.ACTION_EXECUTED_VERIFIED,
                message = "Application ${appName ?: pkg} launched successfully."
            )
        } else {
            CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Failed to launch application ${appName ?: pkg}."
            )
        }
    }

    private fun executeFlashlight(step: PlanStep): CapabilityExecutionResult {
        val enable = step.parameters["enable"]?.toString()?.toBooleanStrictOrNull() ?: true
        val result = flashlightController.setTorch(enable)

        return result.fold(
            onSuccess = { state ->
                val stateText = if (state) "turned on" else "turned off"
                CapabilityExecutionResult(
                    success = true,
                    status = VerificationState.ACTION_EXECUTED_VERIFIED,
                    message = "Flashlight successfully $stateText.",
                    details = mapOf("torch_enabled" to state)
                )
            },
            onFailure = { error ->
                CapabilityExecutionResult(
                    success = false,
                    status = VerificationState.ACTION_FAILED,
                    message = "Flashlight error: ${error.message}"
                )
            }
        )
    }

    suspend fun executeWhatsAppSend(
        step: PlanStep,
        stepListener: ((String) -> Unit)? = null
    ): CapabilityExecutionResult {
        val recipient = step.parameters["recipient"]?.toString() ?: "contact"
        val message = step.parameters["message"]?.toString() ?: "hi"
        val isConfirmed = step.parameters["confirmed"]?.toString()?.toBooleanStrictOrNull() ?: false

        val res = whatsAppAutomation.executeSendMessage(
            recipientName = recipient,
            messageText = message,
            autonomyLevel = securePrefs.autonomyLevel,
            isConfirmedByUser = isConfirmed,
            stepListener = stepListener
        )

        return when (res) {
            is WhatsAppAutomationResult.Success -> CapabilityExecutionResult(
                success = true,
                status = res.verification,
                message = res.message
            )
            is WhatsAppAutomationResult.ContactAmbiguity -> CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Multiple contacts match '${res.query}': ${res.matchingContacts.joinToString(", ")}. Please specify which one.",
                details = mapOf("ambiguous_contacts" to res.matchingContacts)
            )
            is WhatsAppAutomationResult.ConfirmationNeeded -> CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_EXECUTED_UNVERIFIED,
                message = "Confirmation required: Send '$message' to $recipient?",
                details = mapOf("requires_confirmation" to true, "recipient" to recipient, "message" to message)
            )
            is WhatsAppAutomationResult.Failure -> CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = res.reason
            )
        }
    }

    private fun executeUiClick(step: PlanStep): CapabilityExecutionResult {
        val service = HarmaAccessibilityService.instance
            ?: return CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Accessibility service is not active."
            )

        val targetText = step.parameters["text"]?.toString()
        val targetId = step.parameters["view_id"]?.toString()

        val node = if (!targetText.isNullOrBlank()) {
            service.findNodesByText(targetText).firstOrNull()
        } else if (!targetId.isNullOrBlank()) {
            service.findNodesByViewId(targetId).firstOrNull()
        } else null

        return if (node != null && service.clickNode(node)) {
            CapabilityExecutionResult(
                success = true,
                status = VerificationState.ACTION_EXECUTED_VERIFIED,
                message = "Clicked target element."
            )
        } else {
            CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Could not find or click target element."
            )
        }
    }

    private fun executeTextInput(step: PlanStep): CapabilityExecutionResult {
        val service = HarmaAccessibilityService.instance
            ?: return CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Accessibility service is not active."
            )

        val text = step.parameters["text"]?.toString() ?: ""
        val node = service.findFirstClickableMatching { it.isEditable }

        return if (node != null && service.inputText(node, text)) {
            CapabilityExecutionResult(
                success = true,
                status = VerificationState.ACTION_EXECUTED_VERIFIED,
                message = "Text input applied."
            )
        } else {
            CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Editable input element not found."
            )
        }
    }

    private fun executeGlobalAction(action: String): CapabilityExecutionResult {
        val service = HarmaAccessibilityService.instance
            ?: return CapabilityExecutionResult(
                success = false,
                status = VerificationState.ACTION_FAILED,
                message = "Accessibility service is not active."
            )

        val success = when (action) {
            "BACK" -> service.performBack()
            "HOME" -> service.performHome()
            "RECENTS" -> service.performRecents()
            else -> false
        }

        return CapabilityExecutionResult(
            success = success,
            status = if (success) VerificationState.ACTION_EXECUTED_VERIFIED else VerificationState.ACTION_FAILED,
            message = "Global action $action performed."
        )
    }
}
