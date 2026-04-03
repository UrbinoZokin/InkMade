import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/provisioning_controller.dart';
import '../../widgets/state_chip.dart';
import '../../widgets/wizard_scaffold.dart';

class ReviewApplyStep extends StatelessWidget {
  const ReviewApplyStep({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();
    final data = controller.formData;

    return WizardScaffold(
      title: 'Review and apply',
      subtitle:
          'Review your choices, then apply setup to finish.',
      nextStepHint: 'Final step: Click apply and wait for confirmation.',
      error: controller.errorMessage,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StateChip(message: controller.lastDeviceState),
          const SizedBox(height: 12),
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text('Wi‑Fi SSID: ${data.wifiSsid}'),
                  Text('Google Device Flow: ${controller.lastDeviceState?.state}'),
                  Text('iCloud User: ${data.iCloudUser}'),
                  Text('Timezone: ${data.settings.timezone}'),
                  Text('Sleep: ${data.settings.sleepStart} → ${data.settings.sleepEnd}'),
                  Text('Rotation: ${data.settings.rotate}'),
                  Text('Refresh every: ${data.settings.pollIntervalMinutes} min'),
                  Text('Deep-clean cron: ${data.settings.deepCleanCron}'),
                ],
              ),
            ),
          ),
          const SizedBox(height: 12),
          FilledButton.icon(
            onPressed: controller.isBusy ? null : controller.apply,
            icon: const Icon(Icons.check_circle_outline),
            label: const Text('Apply Setup and Finish'),
          ),
        ],
      ),
    );
  }
}
