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
      ),
      body: Row(
        children: [
          SizedBox(
            width: 260,
            child: Stepper(
              currentStep: controller.currentStep.index,
              controlsBuilder: (_, __) => const SizedBox.shrink(),
              steps: WizardStep.values
                  .map((step) => Step(
                        title: Text(_titleFor(step)),
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
        return 'Scan & Connect';
      case WizardStep.pairPin:
        return 'Pair PIN';
      case WizardStep.wifi:
        return 'Wi‑Fi';
      case WizardStep.googleAuth:
        return 'Google Auth';
      case WizardStep.icloud:
        return 'iCloud';
      case WizardStep.deviceSettings:
        return 'Device Settings';
      case WizardStep.reviewApply:
        return 'Review & Apply';
    }
  }
}
