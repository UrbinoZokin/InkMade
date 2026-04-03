import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../models/provisioning_models.dart';
import '../state/provisioning_controller.dart';
import 'steps/device_settings_step.dart';
import 'steps/google_auth_step.dart';
import 'steps/icloud_step.dart';
import 'steps/pair_pin_step.dart';
import 'steps/review_apply_step.dart';
import 'steps/scan_connect_step.dart';
import 'steps/wifi_step.dart';

class ProvisioningWizardScreen extends StatelessWidget {
  const ProvisioningWizardScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Inky Impressions Setup Wizard'),
        actions: [
          TextButton.icon(
            onPressed: () => _showAboutHelp(context),
            icon: const Icon(Icons.help_outline),
            label: const Text('About / Help'),
          ),
          const SizedBox(width: 12),
        ],
      ),
      body: Row(
        children: [
          SizedBox(
            width: 300,
            child: Stepper(
              currentStep: controller.currentStep.index,
              controlsBuilder: (_, __) => const SizedBox.shrink(),
              steps: WizardStep.values
                  .map((step) => Step(
                        title: Text(_titleFor(step)),
                        subtitle: Text(_subtitleFor(step)),
                        content: const SizedBox.shrink(),
                        isActive: controller.currentStep.index >= step.index,
                      ))
                  .toList(),
            ),
          ),
          const VerticalDivider(width: 1),
          Expanded(child: _contentFor(controller.currentStep)),
        ],
      ),
    );
  }

  Widget _contentFor(WizardStep step) {
    switch (step) {
      case WizardStep.scanConnect:
        return const ScanConnectStep();
      case WizardStep.pairPin:
        return const PairPinStep();
      case WizardStep.wifi:
        return const WifiStep();
      case WizardStep.googleAuth:
        return const GoogleAuthStep();
      case WizardStep.icloud:
        return const ICloudStep();
      case WizardStep.deviceSettings:
        return const DeviceSettingsStep();
      case WizardStep.reviewApply:
        return const ReviewApplyStep();
    }
  }

  String _titleFor(WizardStep step) {
    switch (step) {
      case WizardStep.scanConnect:
        return '1) Find Device';
      case WizardStep.pairPin:
        return '2) Confirm Pairing Code';
      case WizardStep.wifi:
        return '3) Connect to Wi‑Fi';
      case WizardStep.googleAuth:
        return '4) Link Google Calendar';
      case WizardStep.icloud:
        return '5) Link iCloud Calendar';
      case WizardStep.deviceSettings:
        return '6) Choose Device Settings';
      case WizardStep.reviewApply:
        return '7) Review and Finish';
    }
  }

  String _subtitleFor(WizardStep step) {
    switch (step) {
      case WizardStep.scanConnect:
        return 'Power on and connect';
      case WizardStep.pairPin:
        return 'Enter the 6-digit PIN';
      case WizardStep.wifi:
        return 'Send home network details';
      case WizardStep.googleAuth:
        return 'Optional calendar link';
      case WizardStep.icloud:
        return 'Optional calendar link';
      case WizardStep.deviceSettings:
        return 'Timezone and refresh settings';
      case WizardStep.reviewApply:
        return 'Apply configuration to device';
    }
  }

  void _showAboutHelp(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('About Inky Impressions Setup'),
        content: const SingleChildScrollView(
          child: Text(
            'This app helps you set up your Inky Impressions display over Bluetooth.\n\n'
            'You will go step-by-step to:\n'
            '• connect to your device\n'
            '• enter Wi‑Fi details\n'
            '• link calendar providers\n'
            '• set timezone and refresh options\n'
            '• apply everything to the device\n\n'
            'If you see an error, keep the device powered on, stay within Bluetooth range, and try the current step again.',
          ),
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Got it'),
          ),
        ],
      ),
    );
  }
}
