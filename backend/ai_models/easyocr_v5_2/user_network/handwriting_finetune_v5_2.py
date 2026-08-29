"""
ESSCAN custom EasyOCR recognition network for the user's V5.2 checkpoint.

Architecture must match the training checkpoint exactly:
None -> VGG -> 2x BiLSTM -> CTC
input_channel=1, output_channel=256, hidden_size=256, num_class=97.

This file intentionally contains only the VGG + BiLSTM components needed by
the V5.2 checkpoint. It is compatible with EasyOCR's user_network mechanism.
"""

import torch.nn as nn
import torch.nn.functional as F


class VGG_FeatureExtractor(nn.Module):
    """VGG feature extractor used by the V5.2 training trainer."""
    def __init__(self, input_channel, output_channel=512):
        super(VGG_FeatureExtractor, self).__init__()
        self.output_channel = [
            int(output_channel / 8),
            int(output_channel / 4),
            int(output_channel / 2),
            output_channel,
        ]

        self.ConvNet = nn.Sequential(
            nn.Conv2d(input_channel, self.output_channel[0], 3, 1, 1),
            nn.ReLU(True),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(self.output_channel[0], self.output_channel[1], 3, 1, 1),
            nn.ReLU(True),
            nn.MaxPool2d(2, 2),

            nn.Conv2d(self.output_channel[1], self.output_channel[2], 3, 1, 1),
            nn.ReLU(True),

            nn.Conv2d(self.output_channel[2], self.output_channel[2], 3, 1, 1),
            nn.ReLU(True),
            nn.MaxPool2d((2, 1), (2, 1)),

            nn.Conv2d(
                self.output_channel[2],
                self.output_channel[3],
                3, 1, 1, bias=False
            ),
            nn.BatchNorm2d(self.output_channel[3]),
            nn.ReLU(True),

            nn.Conv2d(
                self.output_channel[3],
                self.output_channel[3],
                3, 1, 1, bias=False
            ),
            nn.BatchNorm2d(self.output_channel[3]),
            nn.ReLU(True),
            nn.MaxPool2d((2, 1), (2, 1)),

            nn.Conv2d(
                self.output_channel[3],
                self.output_channel[3],
                2, 1, 0
            ),
            nn.ReLU(True),
        )

    def forward(self, input):
        return self.ConvNet(input)


class BidirectionalLSTM(nn.Module):
    """BiLSTM block used by the V5.2 training trainer."""
    def __init__(self, input_size, hidden_size, output_size):
        super(BidirectionalLSTM, self).__init__()
        self.rnn = nn.LSTM(
            input_size,
            hidden_size,
            bidirectional=True,
            batch_first=True,
        )
        self.linear = nn.Linear(hidden_size * 2, output_size)

    def forward(self, input):
        try:
            self.rnn.flatten_parameters()
        except Exception:
            pass

        recurrent, _ = self.rnn(input)
        output = self.linear(recurrent)
        return output


class Model(nn.Module):
    """
    EasyOCR custom recognition model API.

    The parameter names intentionally mirror trainer/model.py so the
    DataParallel V5.2 checkpoint loads strictly.
    """
    def __init__(
        self,
        num_class,
        input_channel=1,
        output_channel=256,
        hidden_size=256,
        **kwargs,
    ):
        super(Model, self).__init__()

        self.FeatureExtraction = VGG_FeatureExtractor(
            input_channel,
            output_channel,
        )

        self.FeatureExtraction_output = output_channel

        self.AdaptiveAvgPool = nn.AdaptiveAvgPool2d((None, 1))

        self.SequenceModeling = nn.Sequential(
            BidirectionalLSTM(
                self.FeatureExtraction_output,
                hidden_size,
                hidden_size,
            ),
            BidirectionalLSTM(
                hidden_size,
                hidden_size,
                hidden_size,
            ),
        )

        self.SequenceModeling_output = hidden_size

        self.Prediction = nn.Linear(
            self.SequenceModeling_output,
            num_class,
        )

    def forward(self, input, text=None, is_train=True):
        visual_feature = self.FeatureExtraction(input)

        visual_feature = self.AdaptiveAvgPool(
            visual_feature.permute(0, 3, 1, 2)
        )

        visual_feature = visual_feature.squeeze(3)

        contextual_feature = self.SequenceModeling(
            visual_feature
        )

        prediction = self.Prediction(
            contextual_feature.contiguous()
        )

        return prediction
