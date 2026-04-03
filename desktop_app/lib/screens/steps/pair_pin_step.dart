import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../state/provisioning_controller.dart';
import '../../widgets/state_chip.dart';
import '../../widgets/wizard_scaffold.dart';

class PairPinStep extends StatefulWidget {
  const PairPinStep({super.key});

  @override
  State<PairPinStep> createState() => _PairPinStepState();
}

class _PairPinStepState extends State<PairPinStep> {
  final _formKey = GlobalKey<FormState>();
  final _pinController = TextEditingController();

  @override
  void dispose() {
    _pinController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final controller = context.watch<ProvisioningController>();

    return WizardScaffold(
      title: 'Enter pairing PIN',
      subtitle: 'Enter the setup PIN shown on your display screen.',
      nextStepHint: 'Next: Continue to Wi‑Fi after pairing succeeds.',
      error: controller.errorMessage,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          StateChip(message: controller.lastDeviceState),
          const SizedBox(height: 16),
          Form(
            key: _formKey,
            child: SizedBox(
              width: 360,
              child: TextFormField(
                controller: _pinController,
                decoration: const InputDecoration(
                  labelText: '6-digit setup PIN',
                  border: OutlineInputBorder(),
                ),
                keyboardType: TextInputType.number,
                validator: (value) {
                  final text = (value ?? '').trim();
                  if (text.length != 6) return 'Please enter exactly 6 digits.';
                  if (!RegExp(r'^\d{6}$').hasMatch(text)) {
                    return 'PIN can only contain numbers.';
                  }
                  return null;
                },
              ),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              FilledButton(
                onPressed: controller.isBusy
                    ? null
                    : () async {
                        if (!_formKey.currentState!.validate()) return;
                        controller.formData.pin = _pinController.text.trim();
                        await controller.sendPairPin();
                      },
                child: const Text('Pair Device'),
              ),
              const SizedBox(width: 8),
              OutlinedButton(
                onPressed: controller.isBusy ? null : controller.nextStep,
                child: const Text('Continue to Wi‑Fi'),
              ),
            ],
          ),
        ],
      ),
    );
  }
}
