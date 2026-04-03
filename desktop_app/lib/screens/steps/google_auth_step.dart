import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/provisioning_controller.dart';
import '../../widgets/state_chip.dart';
import '../../widgets/wizard_scaffold.dart';

class GoogleAuthStep extends StatelessWidget {
  const GoogleAuthStep({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();
    final msg = controller.lastDeviceState;

    return WizardScaffold(
      title: 'Google Calendar authorization',
      subtitle:
          'Link Google Calendar using the on-screen code and link below.',
      nextStepHint: 'Next: Optionally link iCloud, then continue.',
      error: controller.errorMessage,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StateChip(message: msg),
          const SizedBox(height: 12),
          if (msg?.state == 'oauth_device')
            Card(
              child: Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text('Verification URL: ${msg?.verificationUrl ?? '-'}'),
                    const SizedBox(height: 6),
                    Text('User Code: ${msg?.userCode ?? '-'}'),
                    const SizedBox(height: 6),
                    Text('Expires in: ${msg?.expiresIn ?? '-'} seconds'),
                  ],
                ),
              ),
            ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            children: [
              FilledButton(
                onPressed: controller.isBusy
                    ? null
                    : controller.startGoogleDeviceFlow,
                child: const Text('Start Google Sign-In'),
              ),
              OutlinedButton(
                onPressed: controller.isBusy
                    ? null
                    : controller.cancelGoogleDeviceFlow,
                child: const Text('Cancel Google Sign-In'),
              ),
              OutlinedButton(
                onPressed: controller.isBusy ? null : controller.nextStep,
                child: const Text('Continue to iCloud Setup'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
