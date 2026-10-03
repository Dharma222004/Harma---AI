package ai.harma.app.ui

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import ai.harma.app.data.local.SecurePreferences
import ai.harma.app.data.model.ConversationMessage
import ai.harma.app.data.model.VoiceState
import ai.harma.app.ui.screens.ConversationScreen
import ai.harma.app.ui.screens.HomeScreen
import ai.harma.app.ui.screens.PermissionScreen
import ai.harma.app.ui.screens.SettingsScreen

sealed class Screen(val route: String) {
    object Home : Screen("home")
    object Conversation : Screen("conversation")
    object Permissions : Screen("permissions")
    object Settings : Screen("settings")
}

@Composable
fun HarmaNavGraph(
    navController: NavHostController = rememberNavController(),
    voiceState: VoiceState,
    connectionState: String,
    messages: List<ConversationMessage>,
    executionSteps: List<String>,
    securePrefs: SecurePreferences,
    onMicClick: () -> Unit,
    onSendMessage: (String) -> Unit,
    onUrlUpdated: (String) -> Unit
) {
    NavHost(
        navController = navController,
        startDestination = Screen.Home.route
    ) {
        composable(Screen.Home.route) {
            HomeScreen(
                voiceState = voiceState,
                connectionState = connectionState,
                recentSteps = executionSteps,
                onMicClick = onMicClick,
                onQuickPromptClick = onSendMessage,
                onNavigateConversation = { navController.navigate(Screen.Conversation.route) },
                onNavigatePermissions = { navController.navigate(Screen.Permissions.route) },
                onNavigateSettings = { navController.navigate(Screen.Settings.route) }
            )
        }

        composable(Screen.Conversation.route) {
            ConversationScreen(
                messages = messages,
                onSendMessage = onSendMessage,
                onMicClick = onMicClick,
                onBack = { navController.popBackStack() }
            )
        }

        composable(Screen.Permissions.route) {
            PermissionScreen(
                onBack = { navController.popBackStack() }
            )
        }

        composable(Screen.Settings.route) {
            SettingsScreen(
                securePrefs = securePrefs,
                onUrlUpdated = onUrlUpdated,
                onBack = { navController.popBackStack() }
            )
        }
    }
}
