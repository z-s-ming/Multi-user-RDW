using System;

public static class ExperimentSeedSequence
{
    public const int FixedSeedCount = 100;

    public static int GetSeed(int trialIndex, bool reproducible)
    {
        if (!reproducible)
            return CreateNonReproducibleSeed();

        return FixedSeeds[PositiveModulo(trialIndex, FixedSeeds.Length)];
    }

    private static int CreateNonReproducibleSeed()
    {
        return Guid.NewGuid().GetHashCode() ^ Environment.TickCount;
    }

    private static int PositiveModulo(int value, int divisor)
    {
        int result = value % divisor;
        return result < 0 ? result + divisor : result;
    }

    private static readonly int[] FixedSeeds =
    {
        918273, 47291, 683504, 129887, 75531, 940216, 310579, 58642, 801337, 244908,
        679115, 153806, 92044, 731662, 488301, 26719, 604850, 385276, 99703, 818421,
        56318, 709944, 432607, 174250, 891536, 320084, 61027, 548793, 236419, 96572,
        782640, 407151, 134698, 694025, 251307, 849916, 37052, 523688, 912470, 160239,
        445816, 77293, 638951, 299604, 857120, 48166, 705382, 193547, 928611, 356204,
        67435, 514992, 241760, 789306, 117428, 602817, 33495, 861739, 450268, 97314,
        716805, 284631, 55972, 930486, 375219, 142067, 806544, 49031, 658320, 215794,
        884602, 327158, 73184, 596470, 268905, 945113, 40126, 753891, 187604, 629358,
        31047, 812965, 456730, 102589, 691244, 238016, 97053, 540871, 366492, 904725,
        15327, 776408, 428196, 83561, 617209, 292754, 958430, 64108, 504377, 139862
    };
}
