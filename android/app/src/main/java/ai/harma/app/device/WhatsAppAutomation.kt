package ai.harma.app.device

import android.content.Context
import android.view.accessibility.AccessibilityNodeInfo
import ai.harma.app.data.model.AutonomyLevel
import ai.harma.app.data.model.VerificationState
import kotlinx.coroutines.delay

/**
 * Result data class for WhatsApp automation steps
 */
sealed class WhatsAppAutomationResult {
    data class Success(val message: String, val verification: VerificationState) : WhatsAppAutomationResult()
    data class ContactAmbiguity(val query: String, val matchingContacts: List<String>) : WhatsAppAutomationResult()
    data class ConfirmationNeeded(val recipient: String, val message: String) : WhatsAppAutomationResult()
    data class Failure(val reason: String, val requiresRecovery: Boolean = false) : WhatsAppAutomationResult()
}

/**
 * Robust WhatsApp Device Capability Implementation
 * Uses semantic accessibility node inspection, confirmation policy check,
 * contact disambiguation, duplicate-send protection, and post-action verification.
 */
class WhatsAppAutomation(
    private val context: Context,
    private val appLauncher: AppLauncher
) {

    companion object {
        const val WHATSAPP_PACKAGE = "com.whatsapp"
    }

    suspend fun executeSendMessage(
        recipientName: String,
        messageText: String,
        autonomyLevel: AutonomyLevel,
        isConfirmedByUser: Boolean = false,
        stepListener: ((String) -> Unit)? = null
    ): WhatsAppAutomationResult {

        val service = HarmaAccessibilityService.instance
            ?: return WhatsAppAutomationResult.Failure("Accessibility Service is not enabled. Please enable it in Settings.")

        // 1. Launch WhatsApp
        stepListener?.invoke("Opening WhatsApp...")
        val launched = appLauncher.launchPackage(WHATSAPP_PACKAGE)
        if (!launched) {
            return WhatsAppAutomationResult.Failure("WhatsApp application is not installed on this device.")
        }

        // Wait for UI to settle
        delay(1200)

        // 2. Observe active window
        var root = service.rootInActiveWindow
        if (root == null || root.packageName?.toString() != WHATSAPP_PACKAGE) {
            delay(1000)
            root = service.rootInActiveWindow
            if (root == null || root.packageName?.toString() != WHATSAPP_PACKAGE) {
                return WhatsAppAutomationResult.Failure("WhatsApp failed to bring its window to foreground.")
            }
        }

        // 3. Check for search trigger (Search button or Search Bar)
        stepListener?.invoke("Searching for recipient: $recipientName...")
        val searchNode = findSearchNode(service)
        if (searchNode != null) {
            service.clickNode(searchNode)
            delay(500)
        }

        // 4. Find the search input field and enter the recipient name
        val searchInput = findSearchInputField(service)
        if (searchInput != null) {
            service.inputText(searchInput, recipientName)
            delay(1200) // allow search results to filter
        } else {
            stepListener?.invoke("Search field not found directly; scanning visible contacts...")
        }

        // 5. Inspect search results and resolve contact ambiguity
        val candidateContacts = findContactCandidates(service, recipientName)
        if (candidateContacts.isEmpty()) {
            return WhatsAppAutomationResult.Failure("Could not find contact '$recipientName' in WhatsApp.")
        }

        // If multiple distinct contacts match and neither is an exact singular match
        val distinctMatches = candidateContacts.map { it.text?.toString()?.trim().orEmpty() }
            .filter { it.contains(recipientName, ignoreCase = true) }
            .distinct()

        if (distinctMatches.size > 1) {
            return WhatsAppAutomationResult.ContactAmbiguity(recipientName, distinctMatches)
        }

        // 6. Click the best matching contact
        stepListener?.invoke("Opening conversation with ${distinctMatches.firstOrNull() ?: recipientName}...")
        val targetContactNode = candidateContacts.first()
        service.clickNode(targetContactNode)
        delay(1200) // wait for conversation view to load

        // 7. Locate Message Composer
        val composer = findMessageComposer(service)
            ?: return WhatsAppAutomationResult.Failure("Conversation message composer could not be found.")

        // 8. Consequential Action / Autonomy Policy Check
        // If autonomy is not AUTONOMOUS, we must require user confirmation before sending
        if (autonomyLevel != AutonomyLevel.AUTONOMOUS && !isConfirmedByUser) {
            return WhatsAppAutomationResult.ConfirmationNeeded(recipientName, messageText)
        }

        // 9. Duplicate Action Protection
        // Check if an identical message was already recently placed in this chat
        val visibleTexts = service.getVisibleTexts()
        if (visibleTexts.takeLast(5).any { it.equals(messageText.trim(), ignoreCase = true) }) {
            stepListener?.invoke("Duplicate message protection: identical message already sent.")
            return WhatsAppAutomationResult.Success(
                message = "Message already delivered to $recipientName (Duplicate prevented).",
                verification = VerificationState.ACTION_EXECUTED_VERIFIED
            )
        }

        // 10. Enter message text into composer
        stepListener?.invoke("Typing message...")
        service.inputText(composer, messageText)
        delay(600)

        // 11. Find Send Button (Content Description 'Send' or ID 'send')
        stepListener?.invoke("Sending message...")
        val sendButton = findSendButton(service)
            ?: return WhatsAppAutomationResult.Failure("Send button not found or disabled.")

        service.clickNode(sendButton)
        delay(1000)

        // 12. Strict Outcome Verification (Never claim success solely based on click)
        stepListener?.invoke("Verifying message delivery in conversation...")
        val updatedTexts = service.getVisibleTexts()
        val messageFoundInTimeline = updatedTexts.any { it.equals(messageText.trim(), ignoreCase = true) }

        return if (messageFoundInTimeline) {
            WhatsAppAutomationResult.Success(
                message = "Message '$messageText' sent and verified in WhatsApp chat with $recipientName.",
                verification = VerificationState.ACTION_EXECUTED_VERIFIED
            )
        } else {
            // Unverified state: click was executed, but text not yet observed in bubbles
            WhatsAppAutomationResult.Success(
                message = "Send action triggered for $recipientName. Awaiting chat receipt verification.",
                verification = VerificationState.ACTION_EXECUTED_UNVERIFIED
            )
        }
    }

    private fun findSearchNode(service: HarmaAccessibilityService): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        return service.findFirstClickableMatching { node ->
            val desc = node.contentDescription?.toString()?.lowercase() ?: ""
            val id = node.viewIdResourceName?.lowercase() ?: ""
            desc.contains("search") || id.contains("menuitem_search") || id.contains("search_button")
        }
    }

    private fun findSearchInputField(service: HarmaAccessibilityService): AccessibilityNodeInfo? {
        val root = service.rootInActiveWindow ?: return null
        return service.findFirstClickableMatching { node ->
            val id = node.viewIdResourceName?.lowercase() ?: ""
            val text = node.text?.toString()?.lowercase() ?: ""
            node.isEditable || id.contains("search_src_text") || text.contains("search")
        }
    }

    private fun findContactCandidates(service: HarmaAccessibilityService, query: String): List<AccessibilityNodeInfo> {
        val root = service.rootInActiveWindow ?: return emptyList()
        val candidates = mutableListOf<AccessibilityNodeInfo>()

        fun walk(node: AccessibilityNodeInfo) {
            val text = node.text?.toString()
            if (!text.isNullOrBlank() && text.contains(query, ignoreCase = true)) {
                // Ensure it's not the search bar itself
                if (!node.isEditable) {
                    candidates.add(node)
                }
            }
            for (i in 0 until node.childCount) {
                val child = node.getChild(i) ?: continue
                walk(child)
            }
        }

        walk(root)
        return candidates
    }

    private fun findMessageComposer(service: HarmaAccessibilityService): AccessibilityNodeInfo? {
        return service.findFirstClickableMatching { node ->
            val id = node.viewIdResourceName?.lowercase() ?: ""
            val text = node.text?.toString()?.lowercase() ?: ""
            val desc = node.contentDescription?.toString()?.lowercase() ?: ""
            node.isEditable ||
                    id.contains("entry") ||
                    id.contains("message_text") ||
                    text.contains("type a message") ||
                    desc.contains("type a message")
        }
    }

    private fun findSendButton(service: HarmaAccessibilityService): AccessibilityNodeInfo? {
        return service.findFirstClickableMatching { node ->
            val id = node.viewIdResourceName?.lowercase() ?: ""
            val desc = node.contentDescription?.toString()?.lowercase() ?: ""
            desc.contains("send") || id.contains("send")
        }
    }
}
