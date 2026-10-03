package ai.harma.app.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Dialog
import ai.harma.app.data.model.ConfirmationRequiredInfo
import ai.harma.app.ui.theme.*

@Composable
fun ConfirmationDialog(
    info: ConfirmationRequiredInfo,
    onConfirm: () -> Unit,
    onCancel: () -> Unit
) {
    Dialog(onDismissRequest = onCancel) {
        Box(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(20.dp))
                .background(HarmaCard)
                .border(1.dp, HarmaBorderLight, RoundedCornerShape(20.dp))
                .padding(24.dp)
        ) {
            Column(horizontalAlignment = Alignment.Start) {
                Text(
                    text = "Confirmation Required",
                    style = MaterialTheme.typography.titleMedium.copy(fontWeight = FontWeight.SemiBold),
                    color = HarmaTextPrimary
                )

                Spacer(modifier = Modifier.height(12.dp))

                Text(
                    text = info.message,
                    style = MaterialTheme.typography.bodyLarge,
                    color = HarmaTextSecondary
                )

                Spacer(modifier = Modifier.height(16.dp))

                // Detail Box
                Column(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(12.dp))
                        .background(HarmaBlack)
                        .border(1.dp, HarmaBorder, RoundedCornerShape(12.dp))
                        .padding(14.dp)
                ) {
                    Text(
                        text = "ACTION: ${info.action_type.uppercase()}",
                        style = MaterialTheme.typography.labelSmall,
                        color = HarmaTextSecondary
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    Text(
                        text = "Target: ${info.target}",
                        style = MaterialTheme.typography.bodyMedium,
                        color = HarmaTextPrimary
                    )
                    info.payload["message"]?.let { msg ->
                        Spacer(modifier = Modifier.height(4.dp))
                        Text(
                            text = "Message: \"$msg\"",
                            style = MaterialTheme.typography.bodyMedium,
                            color = HarmaTextPrimary
                        )
                    }
                }

                Spacer(modifier = Modifier.height(24.dp))

                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(12.dp)
                ) {
                    OutlinedButton(
                        onClick = onCancel,
                        modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.outlinedButtonColors(
                            contentColor = HarmaTextSecondary
                        ),
                        border = androidx.compose.foundation.BorderStroke(1.dp, HarmaBorder)
                    ) {
                        Text("Cancel")
                    }

                    Button(
                        onClick = onConfirm,
                        modifier = Modifier.weight(1f),
                        shape = RoundedCornerShape(12.dp),
                        colors = ButtonDefaults.buttonColors(
                            containerColor = HarmaTextPrimary,
                            contentColor = HarmaBlack
                        )
                    ) {
                        Text("Send", fontWeight = FontWeight.Bold)
                    }
                }
            }
        }
    }
}
